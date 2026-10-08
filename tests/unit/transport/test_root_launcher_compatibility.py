"""Contract tests for root shell entry points without starting Orca.

All scripts are copied into a private tree. Their implementations are replaced
with harmless stubs to test argument forwarding and path quoting.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHERS = (
    "run_braille_bridge.sh",
    "start-orca-remote.sh",
    "start-orca-session.sh",
)


@unittest.skipUnless(shutil.which("bash"), "Bash is required")
class RootLauncherCompatibilityTests(unittest.TestCase):
    def test_root_launchers_only_delegate_to_scripts_linux(self):
        for name in LAUNCHERS:
            with self.subTest(script=name):
                root = ROOT / name
                implementation = ROOT / "scripts" / "linux" / name
                self.assertTrue(root.is_file())
                self.assertTrue(implementation.is_file())
                self.assertTrue(os.access(root, os.X_OK))
                text = root.read_text()
                self.assertIn('exec "$root_dir/scripts/linux/', text)
                self.assertIn('"$@"', text)
                # Avoid duplicate runtime logic in the compatibility layer.
                self.assertNotIn("orca --replace", text)
                self.assertNotIn("AT_SPI_BUS_ADDRESS=", text)

    def test_root_launchers_forward_arguments_and_exit_codes_from_odd_paths(self):
        with tempfile.TemporaryDirectory(prefix="linux-rdaccess launch $ ") as directory:
            repo = Path(directory) / "a 'quoted' repo $!"
            scripts = repo / "scripts" / "linux"
            scripts.mkdir(parents=True)
            marker = repo / "record"
            for name in LAUNCHERS:
                with self.subTest(script=name):
                    shutil.copy2(ROOT / name, repo / name)
                    target = scripts / name
                    target.write_text(
                        '#!/usr/bin/env bash\n'
                        'printf "%s\\\\0" "$@" > "$LRD_LAUNCHER_RECORD"\n'
                        'exit 37\n'
                    )
                    target.chmod(0o755)
                    marker.unlink(missing_ok=True)
                    arguments = ["--check", "two words", "a'b", "dollar$sign", ""]
                    env = dict(os.environ, LRD_LAUNCHER_RECORD=str(marker))
                    result = subprocess.run(
                        ["bash", str(repo / name), *arguments],
                        cwd="/", env=env, capture_output=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 37, result.stderr.decode(errors="replace"))
                    self.assertEqual(marker.read_bytes().split(b"\0")[:-1],
                                     [value.encode() for value in arguments])


if __name__ == "__main__":
    unittest.main()
