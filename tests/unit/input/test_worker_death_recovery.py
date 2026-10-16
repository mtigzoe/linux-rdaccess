"""Issue #61: isolated worker-death recovery (NOT a live Orca test).

The child is a disposable surrogate process. The parent models the transport
notification produced when an Orca-side worker disappears. No DISPLAY, D-Bus,
NVDA, physical braille device, or active Orca session is touched.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from tests.unit.input.test_lifecycle_invariants import LifecycleHarness


_WORKER = (
    "import sys, time; "
    "sys.stdout.write('READY\\n'); sys.stdout.flush(); "
    "time.sleep(60)"
)


class WorkerDeathRecoveryTests(LifecycleHarness, unittest.TestCase):
    def test_child_termination_expires_queued_work_and_releases_keys(self):
        controller = self._lifecycle_controller()
        controller._linux_rdaccess_run_main = lambda func, **kw: func()
        self._key(controller, 0xA2, True)  # remote left Ctrl pressed
        self.assertEqual(
            [pressed for _, key, pressed in self._key_log(controller)
             if key == 0xA2], [True])
        queue, patches = self._fake_glib()
        with patches:
            controller._linux_rdaccess_stop_local_speech()
            proc = subprocess.Popen(
                [sys.executable, "-u", "-c", _WORKER],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(proc.stdout.readline().strip(), "READY")
                proc.terminate()
                proc.wait(timeout=5)
                self.assertIsNotNone(proc.returncode)
                # Model the disconnect event when an actual child dies.
                controller._on_transport_disconnected()
                while queue:
                    queue.pop(0)()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                proc.stderr.close()
        self.assertEqual(
            [pressed for _, key, pressed in self._key_log(controller)
             if key == 0xA2], [True, False])
        # A new transport/session must accept fresh key presses.
        self._reconnect(controller, self.FakeTransport())
        self._key(controller, 0x41, True)
        self._key(controller, 0x41, False)
        self.assertEqual(
            [pressed for _, key, pressed in self._key_log(controller)
             if key == 0x41], [True, False])


if __name__ == "__main__":
    unittest.main()
