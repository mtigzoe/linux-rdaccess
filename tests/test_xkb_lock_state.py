import importlib.util
import pathlib
import unittest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "tools" / "xkb_lock_state.py"
_spec = importlib.util.spec_from_file_location("xkb_lock_state", _PATH)
xkb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xkb)


class DecodeTests(unittest.TestCase):
    def test_num_lock_is_mod2_and_caps_lock_is_lock(self):
        self.assertEqual(xkb.decode_locked_mods(0x00), {"caps_lock": False, "num_lock": False})
        self.assertEqual(xkb.decode_locked_mods(0x10), {"caps_lock": False, "num_lock": True})
        self.assertEqual(xkb.decode_locked_mods(0x02), {"caps_lock": True, "num_lock": False})
        self.assertEqual(xkb.decode_locked_mods(0x12), {"caps_lock": True, "num_lock": True})

    def test_other_locked_modifiers_do_not_count(self):
        self.assertEqual(xkb.decode_locked_mods(0x08 | 0x20 | 0x40),
                         {"caps_lock": False, "num_lock": False})

    def test_format_is_plain_and_reports_only_lock_state(self):
        self.assertEqual(
            xkb.format_state({"caps_lock": False, "num_lock": True}),
            "Caps Lock: off  Num Lock: on")

    def test_no_display_is_an_error_not_a_crash(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            self.assertEqual(xkb.main([]), 1)


if __name__ == "__main__":
    unittest.main()
