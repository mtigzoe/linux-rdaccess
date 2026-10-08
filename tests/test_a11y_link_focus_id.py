import unittest

from a11y_link import NvdaA11yLink


def closed_channel():
    raise RuntimeError("no channel")


class LastFocusIdTests(unittest.TestCase):
    def test_last_focus_id_follows_the_newest_snapshot_even_when_not_ready(self):
        link = NvdaA11yLink(closed_channel)
        self.assertIsNone(link.last_focus_id)
        link.send_focus(focus_id="a", objects=[])
        self.assertEqual(link.last_focus_id, "a")
        link.refresh_focus(focus_id="b", objects=[])
        self.assertEqual(link.last_focus_id, "b")
        link.clear_focus()
        self.assertIsNone(link.last_focus_id)


if __name__ == "__main__":
    unittest.main()
