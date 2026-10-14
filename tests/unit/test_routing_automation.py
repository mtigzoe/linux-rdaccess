"""The coordinator waits for new evidence and never retries a route."""

import unittest
import contextlib
import io
import json
import shlex
from unittest import mock

from linux_rdaccess_core.routing_automation import wait_and_route
from diagnostics.nvda.simulate_message_routing import public_observation, software_check
from diagnostics.nvda import simulate_message_routing as coordinator


def trace(events=(), *, drops=0, control=True):
    return {"result": "connected", "status": {"remote_control_active": control,
            "semantic_braille_negotiated": True}, "braille_trace": {
            "available": True, "dropped": drops, "events": list(events)}}


MESSAGE = {"event": "message_shown", "linux_owned": True, "control": True, "capture": False}


class RoutingAutomationTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.calls = []
        self.traces = iter([trace(), trace([MESSAGE]), trace([MESSAGE])])
        self.last_trace = trace()
        self.route_result = "queued"
        self.client = mock.Mock()

        def operation(action):
            self.calls.append(action)
            if action == "braille_trace":
                self.last_trace = next(self.traces, self.last_trace)
                return self.last_trace
            if action == "braille_outcomes":
                return {"braille_outcomes": {"available": True, "dropped": 0, "events": []}}
            if action == "braille_message_route":
                return {"message_route": {"outcome": self.route_result}}
            self.fail("Unexpected operation")

        self.client.operation.side_effect = operation

    def sleep(self, duration):
        self.now += duration

    def run_wait(self):
        return wait_and_route(self.client, wait_seconds=1, clock=lambda: self.now, sleep=self.sleep)

    def test_new_message_causes_exactly_one_simulated_route(self):
        result = self.run_wait()
        self.assertEqual(self.calls.count("braille_message_route"), 1)
        self.assertTrue(result["simulated"])
        self.assertEqual(result["physical_braille"], "unverified")

    def test_old_message_is_not_reused_as_a_new_test(self):
        self.traces = iter([trace([MESSAGE])])
        result = self.run_wait()
        self.assertEqual(result["outcome"], "no_new_message_no_route_sent")
        self.assertNotIn("braille_message_route", self.calls)

    def test_local_control_or_overflow_prevents_route(self):
        for invalid in (trace(control=False), trace(drops=1)):
            self.traces = iter([trace(), invalid])
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.run_wait()
        self.assertNotIn("braille_message_route", self.calls)

    def test_refused_request_is_not_retried(self):
        self.route_result = "refused"
        result = self.run_wait()
        self.assertEqual(result["route_reply"]["message_route"]["outcome"], "refused")
        self.assertEqual(self.calls.count("braille_message_route"), 1)

    def test_ambiguous_dispatch_exception_is_not_retried(self):
        original = self.client.operation.side_effect

        def fail(action):
            if action == "braille_message_route":
                self.calls.append(action)
                raise TimeoutError("No response after potential execution")
            return original(action)

        self.client.operation.side_effect = fail
        with self.assertRaises(TimeoutError):
            self.run_wait()
        self.assertEqual(self.calls.count("braille_message_route"), 1)

    def test_linux_observation_drops_private_or_unbounded_fields(self):
        result = public_observation({
            "name": "PRIVATE", "text": "PRIVATE", "before_caret": 11, "after_caret": 11,
            "elapsed_ms": float("inf"), "events": [
                {"type": "caret-moved", "caret_offset": 9, "elapsed_ms": 20, "text": "PRIVATE"},
                {"type": "caret-moved", "caret_offset": 10, "elapsed_ms": float("nan")},
            ],
        })
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("elapsed_ms", result)
        self.assertEqual(result["caret_events"], [{"caret_offset": 9, "elapsed_ms": 20}])

    def result_fixture(self):
        return {"route_reply": {"message_route": {"outcome": "queued"}},
                "trace_after": {"available": True, "dropped": 0},
                "outcomes_before": {"events": []},
                "outcomes_after": {"available": True, "dropped": 0,
                                   "events": [{"event": "message_dismissed"}]},
                "linux_observer_exit_code": 0,
                "request_started_utc": "2026-10-14T22:00:05+00:00",
                "linux_ready_received_utc": "2026-10-14T22:00:00+00:00",
                "linux_final_received_utc": "2026-10-14T22:00:45+00:00",
                "linux_observation": {"dropped_events": 0, "same_initial_focus": True,
                                      "focus_changed_during_observation": False,
                                      "before_caret": 11, "after_caret": 11, "caret_events": []}}

    def test_queue_acceptance_alone_is_not_a_software_pass(self):
        result = self.result_fixture()
        self.assertEqual(software_check(result), "pass")
        result["outcomes_after"]["events"] = []
        self.assertEqual(software_check(result), "inconclusive")
        result["outcomes_after"]["events"] = [{"event": "message_dismissed"}]
        result["outcomes_after"]["dropped"] = 1
        self.assertEqual(software_check(result), "inconclusive")

    def test_caret_round_trip_or_remote_action_fails_the_scripted_check(self):
        result = self.result_fixture()
        result["linux_observation"]["caret_events"] = [{"caret_offset": 9}, {"caret_offset": 11}]
        self.assertEqual(software_check(result), "fail")
        result["linux_observation"]["caret_events"] = []
        result["outcomes_after"]["events"].append({"event": "activation_attempted"})
        self.assertEqual(software_check(result), "fail")

    def test_unknown_outcome_or_observer_ending_before_route_is_inconclusive(self):
        result = self.result_fixture()
        result["outcomes_after"]["events"].append({"event": "outcome_unknown"})
        self.assertEqual(software_check(result), "inconclusive")
        result = self.result_fixture()
        result["linux_final_received_utc"] = "2026-10-14T22:00:01+00:00"
        self.assertEqual(software_check(result), "inconclusive")

    def test_complete_coordinator_wires_ssh_ready_before_one_route(self):
        original = self.client.operation.side_effect
        outcome_reads = []

        def operation(action):
            if action == "status":
                return trace()
            if action == "braille_outcomes":
                outcome_reads.append(action)
                events = [] if len(outcome_reads) == 1 else [{"event": "message_dismissed"}]
                return {"braille_outcomes": {"available": True, "dropped": 0, "events": events}}
            return original(action)

        self.client.operation.side_effect = operation
        ready = {"observer": "ready", "application": "mousepad", "input_sent": False, "before_caret": 11}
        final = {"kind": "linux-atspi-caret-observation", "before_caret": 11, "after_caret": 11,
                 "dropped_events": 0, "same_initial_focus": True,
                 "focus_changed_during_observation": False, "events": []}
        process = mock.Mock(stdout=io.StringIO(json.dumps(ready)+'\n'+json.dumps(final)+'\n'))
        process.poll.return_value = 0
        process.wait.return_value = 0
        output = io.StringIO()
        path = "/reviewed checkout/observe_routing.py"
        with mock.patch.object(coordinator.os, "name", "nt"), \
                mock.patch.object(coordinator, "AuthorizedClient", return_value=self.client), \
                mock.patch.object(coordinator.subprocess, "Popen", return_value=process) as start, \
                contextlib.redirect_stdout(output):
            code = coordinator.main(["--execute", "--observer-path", path])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls.count("braille_message_route"), 1)
        self.assertIn("StrictHostKeyChecking=yes", start.call_args.args[0])
        self.assertEqual(shlex.split(start.call_args.args[0][-1])[2], path)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(result["software_check"], "pass")
        self.assertEqual(result["physical_braille"], "unverified")

    def test_unready_linux_observer_prevents_any_route(self):
        self.client.operation.side_effect = lambda action: trace()
        process = mock.Mock(stdout=io.StringIO('{"observer":"unavailable","text":"PRIVATE"}\n'))
        process.poll.return_value = 0
        process.wait.return_value = 0
        output = io.StringIO()
        with mock.patch.object(coordinator.os, "name", "nt"), \
                mock.patch.object(coordinator, "AuthorizedClient", return_value=self.client), \
                mock.patch.object(coordinator.subprocess, "Popen", return_value=process), \
                contextlib.redirect_stdout(output):
            code = coordinator.main(["--execute", "--observer-path", "/reviewed/observe_routing.py"])
        self.assertEqual(code, 2)
        self.client.operation.assert_called_once_with("status")
        self.assertNotIn("PRIVATE", output.getvalue())
