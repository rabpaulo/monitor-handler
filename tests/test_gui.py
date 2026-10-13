"""Drives the real GTK window with a fake backend (needs a display)."""

import os
import unittest
from pathlib import Path

from monitor_handler.backends import xrandr
from monitor_handler.backends.gnome import GnomeBackend, parse_state

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
FIX = Path(__file__).parent / "fixtures"


class FakeBackend(xrandr.XrandrBackend):
    def __init__(self):
        self.applied = []

    def list_outputs(self):
        return xrandr.parse_prop((FIX / "xrandr_prop.txt").read_text())

    def apply(self, outputs):
        self.applied.append(outputs)


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class GuiTest(unittest.TestCase):
    def setUp(self):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        from monitor_handler.gui.app import MainWindow
        Gtk.init()
        self.app = Gtk.Application(application_id="io.github.rabpaulo.MonitorHandler.Test")
        self.backend = FakeBackend()
        self.win = MainWindow(self.app, self.backend, dry_run=True)

    def tearDown(self):
        self.win.destroy()

    @staticmethod
    def pump():
        from gi.repository import GLib
        ctx = GLib.MainContext.default()
        while ctx.iteration(False):
            pass

    def pick(self, choice, value):
        choice.widget.set_selected(choice.values.index(value))
        self.pump()

    def out(self, name):
        return next(o for o in self.win.outputs if o.name == name)

    def test_vertical_secondary_above(self):
        w = self.win
        w._select("HDMI-1")
        self.assertEqual(w.c_side.get(), "right")
        self.assertEqual(w.c_ref.get(), "DP-2")
        self.pick(w.c_rot, 90)
        hd = self.out("HDMI-1")
        self.assertEqual((hd.rotation, hd.x, hd.y), (90, 2560, 0))
        self.pick(w.c_side, "above")
        self.pick(w.c_align, "center")
        dp = self.out("DP-2")
        # HDMI rotated is 1080x1920 and sits centred above DP-2; layout normalised to 0,0
        self.assertEqual((hd.x, hd.y), (740, 0))
        self.assertEqual((dp.x, dp.y), (0, 1920))
        cmd = w.backend.preview(w._final())
        self.assertIn("--output HDMI-1 --mode 1920x1080 --rate 60.00 --pos 740x0 --rotate right", cmd)
        self.assertEqual(w.xrandr_text, cmd)
        self.assertEqual(w.xrandr_label.get_label(), cmd)

    def test_primary_and_resolution(self):
        w = self.win
        w._select("HDMI-1")
        w.chk_primary.set_active(True)
        self.assertTrue(self.out("HDMI-1").primary)
        self.assertFalse(self.out("DP-2").primary)
        w._select("DP-2")
        self.pick(w.c_res, (1920, 1080))
        dp, hd = self.out("DP-2"), self.out("HDMI-1")
        self.assertEqual((dp.width, dp.refresh), (1920, 179.98))
        self.assertEqual(hd.x, 1920)  # neighbour kept attached
        self.pick(w.c_rate, 59.93)
        self.assertEqual(dp.refresh, 59.93)
        self.assertIn("--mode 1920x1080 --rate 59.93", w.xrandr_text)
        w.brightness.set_value(0.7)
        self.assertIn("--brightness 0.70", w.xrandr_text)

    def test_disable_and_reset(self):
        w = self.win
        w._select("DP-2")
        w.sw_enabled.set_active(False)
        self.assertTrue(self.out("HDMI-1").primary)
        self.assertEqual(self.out("HDMI-1").x, 0)
        self.assertIn("--output DP-2 --off", w.backend.preview(w._final()))
        w._reset()
        self.assertTrue(self.out("DP-2").enabled)


class GnomeVariantTest(unittest.TestCase):
    def test_variant_signature(self):
        from tests.test_backends import GnomeTest
        b = GnomeBackend()
        b._serial, b._layout_mode = 7, 1
        outs = parse_state(GnomeTest.STATE)
        v = b._variant(outs)
        self.assertEqual(v.get_type_string(), "(uua(iiduba(ssa{sv}))a{sv})")


if __name__ == "__main__":
    unittest.main()
