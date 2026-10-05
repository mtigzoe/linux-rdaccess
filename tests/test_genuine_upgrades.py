"""Upgrade complete historical output, not a renamed current marker."""
import ast
from pathlib import Path
import tempfile
import unittest

import remote_access

FIXTURES = Path(__file__).parent / 'fixtures/legacy-patches'


class GenuineUpgradeTests(unittest.TestCase):
    def cases(self):
        return (
            ('controller', 'v29', remote_access.patch_legacy_orca_remote_controller, remote_access.legacy_controller_patch_current),
            ('controller', 'v30', remote_access.patch_legacy_orca_remote_controller, remote_access.legacy_controller_patch_current),
            ('local', 'v6', remote_access.patch_legacy_orca_local_machine, remote_access.legacy_local_machine_patch_current),
            ('local', 'v7', remote_access.patch_legacy_orca_local_machine, remote_access.legacy_local_machine_patch_current),
        )

    def test_historical_output_upgrades_privately_and_idempotently(self):
        for name, version, patch, current in self.cases():
            with self.subTest(name=name, version=version), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'patch.py'
                historical = (FIXTURES / f'{name}-{version}.txt').read_text()
                original = (FIXTURES / f'{name}-upstream.txt').read_text()
                path.write_text(historical)
                backup = path.with_name(path.name + '.linux-rdaccess-backup')
                backup.write_text(original)
                backup.chmod(0o644)
                self.assertFalse(current(historical))
                self.assertTrue(patch(path))
                updated = path.read_text()
                self.assertTrue(current(updated))
                ast.parse(updated, feature_version=(3, 10))
                self.assertFalse(patch(path))
                self.assertEqual(path.read_text(), updated)
                self.assertEqual(backup.read_text(), original)
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_or_corrupt_backup_preserves_historical_patch(self):
        for name, version, patch, _ in self.cases():
            for backup_content in (None, 'class broken syntax:\n'):
                with self.subTest(name=name, version=version, backup=backup_content), tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'patch.py'
                    historical = (FIXTURES / f'{name}-{version}.txt').read_text()
                    path.write_text(historical)
                    if backup_content is not None:
                        path.with_name(path.name + '.linux-rdaccess-backup').write_text(backup_content)
                    with self.assertRaises(ValueError):
                        patch(path)
                    self.assertEqual(path.read_text(), historical)

    def test_repository_target_code_accepts_python310_grammar(self):
        root = Path(remote_access.__file__).parent
        files = list(root.glob('*.py')) + list((root / 'diagnostics').glob('*.py'))
        for path in files:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), feature_version=(3, 10))
