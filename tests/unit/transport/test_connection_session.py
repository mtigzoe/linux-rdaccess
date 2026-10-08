"""Focused connection lifecycle tests independent of a running Orca desktop."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from linux_rdaccess_core.connection.session import connect_session, disconnect_session


class SessionLifecycleTests(unittest.TestCase):
    def test_connect_does_not_modify_orca_when_config_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            update = mock.Mock()
            restart = mock.Mock()
            result = connect_session(
                config_path=Path(temp) / "config.json",
                orca_config=Path(temp) / "orca.py",
                restart=True, quiet=True,
                load_config=lambda _: SimpleNamespace(ready=False),
                update_customizations=update, restart_orca=restart,
            )
            self.assertEqual(result, 1)
            update.assert_not_called()
            restart.assert_not_called()

    def test_connect_uses_dependencies_and_optional_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            orca = Path(temp) / "orca.py"
            orca.write_text("# stub\n")
            config = SimpleNamespace(ready=True, host="example.test", port=6837, role="host")
            update = mock.Mock()
            restart = mock.Mock(return_value=7)
            result = connect_session(
                config_path=Path(temp) / "config.json", orca_config=orca,
                restart=False, quiet=True, load_config=lambda _: config,
                update_customizations=update, restart_orca=restart,
            )
            self.assertEqual(result, 0)
            update.assert_called_once_with(config, orca)
            restart.assert_not_called()
            result = connect_session(
                config_path=Path(temp) / "config.json", orca_config=orca,
                restart=True, quiet=True, load_config=lambda _: config,
                update_customizations=update, restart_orca=restart,
            )
            self.assertEqual(result, 7)

    def test_disconnect_missing_config_does_not_modify_or_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            disable = mock.Mock()
            restart = mock.Mock()
            result = disconnect_session(
                orca_config=Path(temp) / "missing.py",
                restart=True, quiet=True, disable_connection=disable,
                restart_orca=restart,
            )
            self.assertEqual(result, 1)
            disable.assert_not_called()
            restart.assert_not_called()

    def test_disconnect_preserves_nonrestart_behavior(self):
        with tempfile.TemporaryDirectory() as temp:
            orca = Path(temp) / "orca.py"
            orca.touch()
            disable = mock.Mock()
            restart = mock.Mock()
            result = disconnect_session(
                orca_config=orca, restart=False, quiet=True,
                disable_connection=disable, restart_orca=restart,
            )
            self.assertEqual(result, 0)
            disable.assert_called_once_with(orca)
            restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
