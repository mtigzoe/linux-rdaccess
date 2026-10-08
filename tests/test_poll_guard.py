import logging
import unittest

from rdaccess_dvc import poll_links


class Link:
    def __init__(self, error=None):
        self.error, self.polls = error, 0

    def poll(self):
        self.polls += 1
        if self.error:
            raise self.error


class PollGuardTests(unittest.TestCase):
    def setUp(self):
        # Other test modules disable logging globally.
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

    def test_one_failing_link_does_not_stop_the_others(self):
        bad, good = Link(OSError("boom")), Link()
        with self.assertLogs("guard-test", level="ERROR"):
            poll_links((("speech", bad), ("braille", good)), logging.getLogger("guard-test"))
        self.assertEqual((bad.polls, good.polls), (1, 1))

    def test_none_links_are_skipped(self):
        good = Link()
        poll_links((("speech", None), ("a11y", good)))
        self.assertEqual(good.polls, 1)

    def test_log_carries_exception_type_not_message(self):
        secret = "private-application-text"
        with self.assertLogs("guard-test", level="ERROR") as logs:
            poll_links((("a11y", Link(RuntimeError(secret))),), logging.getLogger("guard-test"))
        text = "\n".join(logs.output)
        self.assertNotIn(secret, text)
        self.assertIn("RuntimeError", text)

    def test_next_tick_polls_the_failed_link_again(self):
        bad = Link(ValueError("x"))
        links = (("speech", bad),)
        with self.assertLogs("guard-test", level="ERROR"):
            poll_links(links, logging.getLogger("guard-test"))
            poll_links(links, logging.getLogger("guard-test"))
        self.assertEqual(bad.polls, 2)


if __name__ == "__main__":
    unittest.main()
