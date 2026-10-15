"""EWMH readiness and single-request activation regressions, without a display."""

import subprocess
import unittest
from unittest.mock import patch

from tools.diagnostics.x11_window_activation import activate_window


def snapshot(*, wm=100, wm_self=100, supported=True, managed=(12, 13), active=99):
    return {
        "wm": wm,
        "wm_self": wm_self,
        "supported": supported,
        "managed": managed,
        "active": active,
    }


class ActivationFixture:
    def __init__(self, states, *, visible=(13,), attempts=None, command_error=None):
        self.states = states
        self.visible = visible
        self.attempts = attempts or len(states)
        self.command_error = command_error
        self.index = -1
        self.commands = []
        self.diagnostics = []

    def run(self, command, **kwargs):
        self.commands.append(command)
        if command[:2] == ["xprop", "-root"]:
            self.index = min(self.index + 1, len(self.states) - 1)
            state = self.states[self.index]
            supported = (
                "_NET_ACTIVE_WINDOW" if state["supported"] else "_NET_CLIENT_LIST"
            )
            windows = ", ".join(hex(value) for value in state["managed"])
            output = (
                f"_NET_SUPPORTING_WM_CHECK(WINDOW): window id # {hex(state['wm'])}\n"
                f"_NET_SUPPORTED(ATOM) = {supported}\n"
                f"_NET_CLIENT_LIST(WINDOW): window id # {windows}\n"
                f"_NET_ACTIVE_WINDOW(WINDOW): window id # {hex(state['active'])}\n"
            )
        elif command[:2] == ["xprop", "-id"]:
            value = self.states[self.index]["wm_self"]
            output = f"_NET_SUPPORTING_WM_CHECK(WINDOW): window id # {hex(value)}\n"
        else:
            if self.command_error:
                raise self.command_error
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def wait(self, predicate, label):
        for _ in range(self.attempts):
            result = predicate()
            if result:
                return result
        raise AssertionError("Timed out waiting for " + label)

    def activate(self):
        with patch(
            "tools.diagnostics.x11_window_activation.subprocess.run",
            side_effect=self.run,
        ):
            return activate_window(
                lambda: self.visible,
                self.wait,
                "fixture activation",
                diagnostic=self.diagnostics.append,
            )

    @property
    def activations(self):
        return [command for command in self.commands if command[0] == "xdotool"]


class X11WindowActivationTests(unittest.TestCase):
    def test_window_manager_readiness_requires_consistent_supporting_window_and_active_atom(
        self,
    ):
        for state in (snapshot(wm=0), snapshot(wm_self=101), snapshot(supported=False)):
            with self.subTest(state=state):
                fixture = ActivationFixture([state], attempts=3)
                with self.assertRaisesRegex(AssertionError, "fixture activation"):
                    fixture.activate()
                self.assertEqual(fixture.activations, [])
                self.assertFalse(fixture.diagnostics[-1]["success"])

    def test_activation_waits_for_manager_readiness_before_sending_one_request(self):
        fixture = ActivationFixture(
            [
                snapshot(wm_self=101),
                snapshot(supported=False),
                snapshot(),
                snapshot(active=13),
            ]
        )
        self.assertEqual(fixture.activate(), "13")
        self.assertEqual(fixture.activations, [["xdotool", "windowactivate", "13"]])
        self.assertTrue(fixture.diagnostics[-1]["success"])

    def test_target_intersects_visible_candidates_and_managed_clients(self):
        # 12 is managed but hidden; 14 is visible but an unmanaged subordinate.
        fixture = ActivationFixture([snapshot(), snapshot(active=13)], visible=(13, 14))
        self.assertEqual(fixture.activate(), "13")
        self.assertEqual(fixture.activations, [["xdotool", "windowactivate", "13"]])

    def test_no_managed_visible_target_never_sends_activation(self):
        fixture = ActivationFixture([snapshot()], visible=(14,), attempts=3)
        with self.assertRaises(AssertionError):
            fixture.activate()
        self.assertEqual(fixture.activations, [])

    def test_pending_active_property_does_not_repeat_activation(self):
        fixture = ActivationFixture(
            [snapshot(), snapshot(active=12), snapshot(active=13)]
        )
        self.assertEqual(fixture.activate(), "13")
        self.assertEqual(fixture.activations, [["xdotool", "windowactivate", "13"]])

    def test_successful_command_does_not_replace_exact_active_window_verification(self):
        fixture = ActivationFixture([snapshot()], attempts=4)
        with self.assertRaisesRegex(AssertionError, "fixture activation"):
            fixture.activate()
        self.assertEqual(len(fixture.activations), 1)
        self.assertEqual(fixture.diagnostics[-1]["active"], 99)
        self.assertEqual(fixture.diagnostics[-1]["target"], 13)
        self.assertFalse(fixture.diagnostics[-1]["success"])

    def test_stale_active_property_cannot_succeed_after_manager_or_target_disappears(
        self,
    ):
        for unavailable in (
            snapshot(wm=0, active=13),
            snapshot(wm_self=101, active=13),
            snapshot(supported=False, active=13),
            snapshot(managed=(12,), active=13),
        ):
            with self.subTest(unavailable=unavailable):
                fixture = ActivationFixture([snapshot(), unavailable])
                with self.assertRaisesRegex(AssertionError, "fixture activation"):
                    fixture.activate()
                self.assertEqual(
                    fixture.activations, [["xdotool", "windowactivate", "13"]]
                )
                self.assertFalse(fixture.diagnostics[-1]["success"])

    def test_activation_command_failure_and_timeout_are_fatal_with_stderr(self):
        for error in (
            subprocess.CalledProcessError(1, ["xdotool"], stderr="activation denied"),
            subprocess.TimeoutExpired(["xdotool"], 3, stderr=b"activation blocked"),
        ):
            with self.subTest(error=type(error).__name__):
                fixture = ActivationFixture(
                    [snapshot()], attempts=4, command_error=error
                )
                with self.assertRaises(type(error)) as caught:
                    fixture.activate()
                self.assertIs(caught.exception, error)
                self.assertEqual(len(fixture.activations), 1)
                self.assertIn("activation", fixture.diagnostics[-1]["command_stderr"])
                self.assertEqual(fixture.diagnostics[-1]["error"], type(error).__name__)

    def test_property_command_failure_is_fatal_without_activation(self):
        error = subprocess.TimeoutExpired(["xprop"], 3, stderr=b"property blocked")
        fixture = ActivationFixture([snapshot()])
        with (
            patch(
                "tools.diagnostics.x11_window_activation.subprocess.run",
                side_effect=error,
            ),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            activate_window(
                lambda: (13,),
                fixture.wait,
                "fixture activation",
                diagnostic=fixture.diagnostics.append,
            )
        self.assertEqual(fixture.activations, [])
        self.assertFalse(fixture.diagnostics[-1]["activation_sent"])
        self.assertEqual(fixture.diagnostics[-1]["command_stderr"], "property blocked")

    def test_diagnostics_bound_client_ids_and_command_stderr(self):
        fixture = ActivationFixture(
            [snapshot(managed=tuple(range(100)))],
            visible=tuple(range(100)),
            command_error=subprocess.CalledProcessError(
                1, ["xdotool"], stderr="x" * 2000
            ),
        )
        with self.assertRaises(subprocess.CalledProcessError):
            fixture.activate()
        report = fixture.diagnostics[-1]
        self.assertEqual(len(report["managed"]), 32)
        self.assertEqual(len(report["visible_candidates"]), 32)
        self.assertEqual(len(report["command_stderr"]), 1000)


if __name__ == "__main__":
    unittest.main()
