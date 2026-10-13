"""Read-only routing observations preserve privacy and focus lifetime."""

import json
import types
import unittest
from unittest import mock

from linux_rdaccess_core import routing_observer as observer


class TextObject:
    def __init__(self, caret=2, app="Firefox"):
        self.caret = caret
        self.app = app

    def get_text_iface(self):
        return self

    def get_caret_offset(self):
        return self.caret

    def get_application(self):
        return types.SimpleNamespace(get_name=lambda: self.app)

    def get_text(self, *_args):
        raise AssertionError("Text must never be captured")

    def set_caret_offset(self, *_args):
        raise AssertionError("Observer must never route")


def snapshot(obj, role="text"):
    return {"object": obj, "role": role, "name": "private name", "states": ["focused"]}


def event(obj, offset=7, kind="object:text-caret-moved"):
    return types.SimpleNamespace(source=obj, detail1=offset, type=kind, any_data="private event text")


class RoutingObserverTests(unittest.TestCase):
    def setUp(self):
        self.target = TextObject()
        self.before = snapshot(self.target)
        self.observation = observer.RoutingObservation(self.before, clock=lambda: 3.0)

    def test_numeric_caret_events_and_final_position_without_content(self):
        self.observation.event(event(self.target))
        self.target.caret = 7
        result = self.observation.finish(self.before)
        self.assertEqual((result["before_caret"], result["after_caret"]), (2, 7))
        self.assertEqual(result["events"][0]["caret_offset"], 7)
        self.assertTrue(result["same_initial_focus"])
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("pass", result)

    def test_foreign_caret_is_ignored_without_provider_queries(self):
        foreign = mock.Mock()
        self.observation.event(event(foreign))
        self.assertEqual(self.observation.events, [])
        foreign.get_text_iface.assert_not_called()
        foreign.get_name.assert_not_called()

    def test_focus_change_and_return_do_not_claim_caret_round_trip(self):
        other = TextObject()
        self.observation.event(event(other, 1, "object:state-changed:focused"))
        self.observation.event(event(self.target, 1, "object:state-changed:focused"))
        self.observation.event(event(self.target, 7))
        result = self.observation.finish(self.before)
        self.assertTrue(result["same_initial_focus"])
        self.assertTrue(result["focus_changed_during_observation"])
        self.assertIsNone(result["after_caret"])
        self.assertEqual(len(result["events"]), 1)

    def test_changed_or_missing_final_focus_does_not_read_a_new_caret(self):
        other = mock.Mock()
        for after in (snapshot(other), None):
            with self.subTest(after_is_none=after is None):
                result = self.observation.finish(after)
                self.assertFalse(result["same_initial_focus"])
                self.assertIsNone(result["after_caret"])
        other.get_text_iface.assert_not_called()

    def test_password_and_unreadable_providers_are_never_reported(self):
        password = mock.Mock()
        password.get_text_iface.side_effect = AssertionError("private password")
        secret = observer.RoutingObservation(snapshot(password, "password-text"))
        secret.event(event(password, 7))
        self.assertIsNone(secret.finish(snapshot(password, "password-text"))["after_caret"])
        self.assertEqual(secret.events, [])
        password.get_text_iface.assert_not_called()
        unavailable = mock.Mock()
        unavailable.get_text_iface.side_effect = RuntimeError("private provider failure")
        self.assertIsNone(observer.caret_position(snapshot(unavailable)))

    def test_invalid_offsets_and_unsubscribed_events_are_ignored(self):
        for offset in (-1, True, "private", None):
            self.observation.event(event(self.target, offset))
        self.observation.event(event(self.target, 7, "object:text-changed:insert"))
        self.observation.event(event(TextObject(), 0, "object:state-changed:focused"))
        self.assertEqual(self.observation.events, [])

    def test_event_storm_is_bounded_and_disclosed(self):
        for index in range(observer.MAX_EVENTS + 10):
            self.observation.event(event(self.target, index))
        result = self.observation.finish(self.before)
        self.assertEqual(len(result["events"]), observer.MAX_EVENTS)
        self.assertEqual(result["dropped_events"], 10)

    def backend(self, *, after=None, during=None):
        listener = mock.Mock()
        loop = mock.Mock()
        listener_factory = mock.Mock(return_value=listener)
        glib = mock.Mock()
        glib.MainLoop.return_value = loop
        glib.timeout_add.return_value = 17
        glib.MainContext.default.return_value.find_source_by_id.return_value = None
        focus = types.SimpleNamespace(
            read=mock.Mock(side_effect=[self.before, after or self.before]),
            glib=glib,
            atspi=types.SimpleNamespace(EventListener=types.SimpleNamespace(new=listener_factory)),
        )
        if during:
            loop.run.side_effect = lambda: during(listener_factory.call_args.args[0])
        return focus, listener

    def test_backend_emits_ready_then_final_and_deregisters(self):
        def during(callback):
            callback(event(self.target))
            self.target.caret = 7

        focus, listener = self.backend(during=during)
        emitted = []
        result = observer.observe(focus, "firefox", 30, emitted.append)
        self.assertEqual(emitted[0]["observer"], "ready")
        self.assertFalse(emitted[0]["input_sent"])
        self.assertEqual(result["after_caret"], 7)
        self.assertEqual(listener.register.call_args_list, [mock.call(kind) for kind in observer.EVENTS])
        self.assertEqual(listener.deregister.call_args_list, [mock.call(kind) for kind in observer.EVENTS])
        focus.glib.timeout_add.assert_called_once()
        self.assertEqual(focus.glib.timeout_add.call_args.args[0], 30000)

    def test_wrong_target_or_unbounded_duration_never_starts_listener(self):
        for application, duration in (
            ("mousepad", 30),
            ("unknown", 30),
            ("firefox", 0),
            ("firefox", 61),
            ("firefox", float("nan")),
            ("firefox", float("inf")),
        ):
            with self.subTest(application=application, duration=duration):
                focus, _listener = self.backend()
                with self.assertRaises(ValueError):
                    observer.observe(focus, application, duration, lambda _item: None)
                focus.atspi.EventListener.new.assert_not_called()

    def test_partial_registration_failure_cleans_up_previous_listener(self):
        focus, listener = self.backend()
        listener.register.side_effect = [None, RuntimeError("private provider message")]
        with self.assertRaises(RuntimeError):
            observer.observe(focus, "firefox", 30, lambda _item: None)
        listener.deregister.assert_called_once_with(observer.EVENTS[0])
        focus.glib.MainLoop.return_value.run.assert_not_called()

    def test_refused_registration_is_not_reported_ready(self):
        focus, listener = self.backend()
        listener.register.side_effect = [True, False]
        emitted = []
        with self.assertRaisesRegex(ValueError, "registration"):
            observer.observe(focus, "firefox", 30, emitted.append)
        self.assertEqual(emitted, [])
        listener.deregister.assert_called_once_with(observer.EVENTS[0])

    def test_interrupted_collection_removes_pending_timer_and_listeners(self):
        focus, listener = self.backend()
        focus.glib.MainContext.default.return_value.find_source_by_id.return_value = object()
        focus.glib.MainLoop.return_value.run.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            observer.observe(focus, "firefox", 30, lambda _item: None)
        focus.glib.source_remove.assert_called_once_with(17)
        self.assertEqual(listener.deregister.call_count, 2)

    def test_missing_timer_cannot_start_an_unbounded_observer(self):
        focus, listener = self.backend()
        focus.glib.timeout_add.return_value = 0
        emitted = []
        with self.assertRaisesRegex(ValueError, "timer"):
            observer.observe(focus, "firefox", 30, emitted.append)
        self.assertEqual(emitted, [])
        self.assertEqual(listener.deregister.call_count, 2)
        focus.glib.MainLoop.return_value.run.assert_not_called()
