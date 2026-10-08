"""Runtime braille-hook reloads retain the native callable and current owner."""

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from linux_rdaccess_core.connection import remote_access


class BrailleHookReloadTests(unittest.TestCase):
    CONFIG_SOURCE = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "test.invalid"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "synthetic"
connection_type = "slave"
def _dbg(message):
    return
'''

    def runtime(self):
        native_calls = []

        def native_refresh(*args, **kwargs):
            native_calls.append((args, kwargs))
            return "native result"

        braille = types.ModuleType("orca.braille")
        braille.refresh = native_refresh
        orca = types.ModuleType("orca")
        orca.braille = braille
        adapter = types.ModuleType("linux_rdaccess_orca_adapter")
        adapter.OrcaRuntimeAdapter = types.SimpleNamespace(
            braille_cells=lambda **kwargs: [1, 2, 255],
        )
        patch = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.braille": braille,
            "linux_rdaccess_orca_adapter": adapter,
        })
        patch.start()
        self.addCleanup(patch.stop)
        return braille, native_refresh, native_calls

    @staticmethod
    def namespace():
        messages = []
        controller = types.SimpleNamespace(
            transport=types.SimpleNamespace(
                connected=True, connection_type="slave",
                send=lambda **kwargs: messages.append(kwargs),
            ),
        )
        return {"controller": controller, "_dbg": lambda *_args: None}, messages

    def test_repeated_execution_in_same_namespace_preserves_original_result_and_single_send(self):
        braille, original, native_calls = self.runtime()
        namespace, messages = self.namespace()
        for _ in range(3):
            exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
        self.assertEqual(braille.refresh(False, 0, getLinkMask=False), "native result")
        self.assertEqual(native_calls, [((False, 0), {"getLinkMask": False})])
        self.assertEqual(messages, [{"type": "display", "cells": [1, 2, 255]}])
        self.assertIs(braille.refresh._linux_rdaccess_original, original)

    def test_fresh_namespace_replaces_old_controller_without_stacking_forwarders(self):
        braille, original, native_calls = self.runtime()
        old, old_messages = self.namespace()
        new, new_messages = self.namespace()
        exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, old)
        exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, new)
        self.assertEqual(braille.refresh(), "native result")
        self.assertEqual(old_messages, [])
        self.assertEqual(new_messages, [{"type": "display", "cells": [1, 2, 255]}])
        self.assertEqual(len(native_calls), 1)
        self.assertIs(braille.refresh._linux_rdaccess_original, original)

    def test_running_historical_hook_upgrades_without_recapturing_its_wrapper(self):
        for historical in (
            remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V1,
            remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V2,
            remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V3,
        ):
            with self.subTest(marker=historical.splitlines()[0]):
                braille, original, native_calls = self.runtime()
                namespace, messages = self.namespace()
                namespace["controller"]._linux_rdaccess_offer_native_braille = lambda: None
                exec(historical, namespace)
                exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
                self.assertEqual(braille.refresh(), "native result")
                self.assertEqual(messages, [{"type": "display", "cells": [1, 2, 255]}])
                self.assertEqual(len(native_calls), 1)
                self.assertIs(braille.refresh._linux_rdaccess_original, original)

    def test_v3_on_disk_upgrade_preserves_original_private_backup_and_is_idempotent(self):
        original = self.CONFIG_SOURCE + remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V3
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orca-customizations.py"
            path.write_text(original)
            config = remote_access.RemoteAccessConfig(key="synthetic")
            remote_access.update_legacy_orca_customizations(config, path)
            updated = path.read_text()
            self.assertTrue(remote_access.legacy_customization_braille_cells_patch_current(updated))
            self.assertNotIn(remote_access.CUSTOMIZATION_BRAILLE_CELLS_MARKER_V3, updated)
            backup = path.with_name(path.name + ".linux-rdaccess-backup")
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(backup).st_mode & 0o777, 0o600)
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), updated)
            self.assertEqual(backup.read_text(), original)

    def test_tampered_v3_and_v4_hooks_are_rejected_without_writing_config_or_backup(self):
        for source in (
            remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V3.replace("cells=cells", "cells=[]"),
            remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK.replace(
                "_patched_braille_refresh._linux_rdaccess_original = _old_braille_refresh",
                "_patched_braille_refresh._linux_rdaccess_original = _patched_braille_refresh"),
        ):
            with self.subTest(marker=source.splitlines()[0]), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "orca-customizations.py"
                source = self.CONFIG_SOURCE + source
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    remote_access.update_legacy_orca_customizations(
                        remote_access.RemoteAccessConfig(key="synthetic"), path,
                    )
                self.assertEqual(path.read_text(), source)
                self.assertFalse(path.with_name(path.name + ".linux-rdaccess-backup").exists())


if __name__ == "__main__":
    unittest.main()
