import unittest
from pathlib import Path

from monitor_handler.backends import gnome, hyprland, kscreen, sway, wlr_randr, xrandr
from monitor_handler.model import Mode, Output

FIX = Path(__file__).parent / "fixtures"


def by_name(outputs):
    return {o.name: o for o in outputs}


class XrandrTest(unittest.TestCase):
    def setUp(self):
        verbose = "DP-2 connected primary 2560x1440+0+0\n\tBrightness: 0.80\nHDMI-1 connected\n\tBrightness: 1.0\n"
        self.outs = by_name(xrandr.parse_prop((FIX / "xrandr_prop.txt").read_text(), verbose))

    def test_parse(self):
        self.assertEqual(set(self.outs), {"DP-2", "HDMI-1"})
        dp = self.outs["DP-2"]
        self.assertTrue(dp.primary)
        self.assertEqual((dp.width, dp.height, dp.refresh), (2560, 1440, 165.0))
        self.assertEqual(dp.rates_for(2560, 1440), [180.0, 165.0, 120.0, 59.95])
        self.assertEqual(dp.description, "SKG SFPCCB27180")
        self.assertEqual(dp.bit_depth_options, [8, 10, 12, 16])
        self.assertEqual(dp.rgb_range_options, ["Automatic", "Full", "Limited 16:235"])
        self.assertAlmostEqual(dp.brightness, 0.8)
        hd = self.outs["HDMI-1"]
        self.assertEqual((hd.x, hd.y), (2560, 0))
        self.assertTrue(hd.extra["vrr_capable"])

    def test_rotated_header(self):
        text = ("DP-2 connected primary 1440x2560+0+0 left (normal left inverted right x axis y axis) 597mm x 336mm\n"
                "   2560x1440     59.95 + 165.00*\n"
                "HDMI-1 connected (normal left inverted right x axis y axis)\n"
                "   1920x1080     60.00 +\n")
        outs = by_name(xrandr.parse_prop(text))
        self.assertEqual(outs["DP-2"].rotation, 270)
        self.assertEqual((outs["DP-2"].width, outs["DP-2"].height), (2560, 1440))
        self.assertFalse(outs["HDMI-1"].enabled)
        self.assertEqual(outs["HDMI-1"].width, 1920)

    def test_command(self):
        dp, hd = self.outs["DP-2"], self.outs["HDMI-1"]
        hd.rotation, hd.mirror_of = 90, None
        hd.x, hd.y = 2560, 0
        dp.bit_depth = 10
        cmd = xrandr.build_command([dp, hd])
        s = " ".join(cmd)
        self.assertIn("--output DP-2 --mode 2560x1440 --rate 165.00 --pos 0x0 --rotate normal --primary", s)
        self.assertIn("--output HDMI-1 --mode 1920x1080 --rate 60.00 --pos 2560x0 --rotate right", s)
        self.assertIn("max bpc 10", s)
        hd.enabled = False
        self.assertIn("--output HDMI-1 --off", " ".join(xrandr.build_command([dp, hd])))
        hd.enabled, hd.mirror_of = True, "DP-2"
        self.assertIn("--same-as DP-2", " ".join(xrandr.build_command([dp, hd])))


    def test_portable_command_from_other_backend(self):
        outs = by_name(kscreen.parse_json((FIX / "kscreen.json").read_text()))
        cmd = xrandr.build_command(list(outs.values()), driver_props=False)
        self.assertEqual(cmd[:12], ["xrandr", "--output", "DP-2", "--mode", "2560x1440", "--rate", "165.00",
                                    "--pos", "0x0", "--rotate", "normal", "--primary"])
        self.assertNotIn("--set", cmd)
        self.assertNotIn("--brightness", cmd)
        self.assertIn("right", cmd)


class WlrRandrTest(unittest.TestCase):
    def test_parse_and_command(self):
        outs = by_name(wlr_randr.parse_json((FIX / "wlr_randr.json").read_text()))
        dp, hd = outs["DP-1"], outs["HDMI-A-1"]
        self.assertEqual((dp.width, dp.height, dp.scale), (3840, 2160, 1.5))
        self.assertEqual(dp.logical_size(), (2560, 1440))
        self.assertFalse(hd.enabled)
        self.assertEqual(hd.rotation, 90)
        self.assertTrue(hd.vrr)
        hd.enabled, hd.x = True, 2560
        cmd = " ".join(wlr_randr.WlrRandrBackend().commands([dp, hd])[0])
        self.assertIn("--output DP-1 --on --mode 3840x2160@60.000Hz --pos 0,0 --transform normal --scale 1.5", cmd)
        self.assertIn("--output HDMI-A-1 --on --mode 1920x1080@144.000Hz --pos 2560,0 --transform 90", cmd)
        self.assertIn("--adaptive-sync enabled", cmd)


class SwayTest(unittest.TestCase):
    def test_parse_and_command(self):
        outs = by_name(sway.parse_outputs((FIX / "sway.json").read_text()))
        dp, hd = outs["DP-1"], outs["HDMI-A-1"]
        self.assertEqual(dp.logical_size(), (1920, 1080))
        self.assertTrue(dp.hdr_supported)
        self.assertFalse(hd.hdr_supported)
        self.assertEqual(hd.rotation, 270)
        self.assertAlmostEqual(hd.refresh, 144.001)
        dp.hdr, dp.bit_depth = True, 10
        cmds = sway.SwayBackend().commands([dp, hd])
        self.assertEqual(cmds[0][:4], ["swaymsg", "output", "DP-1", "enable"])
        self.assertIn("hdr", cmds[0])
        self.assertIn("render_bit_depth", cmds[0])
        self.assertNotIn("hdr", cmds[1])
        self.assertIn("output HDMI-A-1", sway.SwayBackend().script([dp, hd]))


class HyprlandTest(unittest.TestCase):
    def test_parse_and_rule(self):
        outs = by_name(hyprland.parse_monitors((FIX / "hyprland.json").read_text()))
        dp, hd = outs["DP-1"], outs["HDMI-A-1"]
        self.assertTrue(dp.vrr and dp.hdr)
        self.assertEqual(dp.bit_depth, 10)
        self.assertEqual(hd.rotation, 90)
        self.assertEqual(hyprland.monitor_rule(dp),
                         "DP-1,2560x1440@239.97,0x0,1,transform,0,vrr,1,bitdepth,10,cm,hdr")
        hd.mirror_of = "DP-1"
        self.assertTrue(hyprland.monitor_rule(hd).endswith("mirror,DP-1"))
        hd.enabled = False
        self.assertEqual(hyprland.monitor_rule(hd), "HDMI-A-1,disable")
        cmd = hyprland.HyprlandBackend().commands([hd, dp])[0]
        self.assertTrue(cmd[2].startswith("keyword monitor DP-1"))


class KScreenTest(unittest.TestCase):
    def test_parse_and_command(self):
        outs = by_name(kscreen.parse_json((FIX / "kscreen.json").read_text()))
        self.assertEqual(set(outs), {"DP-2", "HDMI-A-1"})
        dp, hd = outs["DP-2"], outs["HDMI-A-1"]
        self.assertTrue(dp.primary and dp.vrr and dp.vrr_supported and dp.hdr_supported and dp.hdr)
        self.assertEqual(dp.refresh, 165.0)
        self.assertEqual(dp.logical_size(), (2048, 1152))
        self.assertEqual(dp.rgb_range, "Full")
        self.assertEqual(hd.rotation, 90)
        self.assertFalse(hd.vrr_supported)
        args = kscreen.KScreenBackend().commands([dp, hd])[0]
        for a in ("output.DP-2.mode.2", "output.DP-2.position.0,0", "output.DP-2.scale.1.25",
                  "output.DP-2.priority.1", "output.DP-2.vrrpolicy.automatic", "output.DP-2.hdr.enable",
                  "output.DP-2.wcg.enable", "output.DP-2.rgbrange.full", "output.HDMI-A-1.rotation.right"):
            self.assertIn(a, args)
        self.assertNotIn("output.HDMI-A-1.hdr.disable", args)


class GnomeTest(unittest.TestCase):
    STATE = (
        7,
        [
            (("DP-1", "SAM", "Odyssey", "S1"),
             [("2560x1440@165", 2560, 1440, 165.0, 1.0, [1.0, 1.25, 1.5], {"is-current": True, "is-preferred": True}),
              ("2560x1440@165-vrr", 2560, 1440, 165.0, 1.0, [1.0, 1.25], {"refresh-rate-mode": "variable"}),
              ("1920x1080@60", 1920, 1080, 60.0, 1.0, [1.0], {})],
             {"display-name": "Samsung 27\"", "supported-color-modes": [0, 1], "color-mode": 0}),
            (("HDMI-1", "AOC", "24G2", "S2"),
             [("1920x1080@60", 1920, 1080, 60.0, 1.0, [1.0, 2.0], {"is-current": True})],
             {"display-name": "AOC 24\""}),
            (("eDP-1", "BOE", "x", "S3"),
             [("1920x1080@60", 1920, 1080, 60.0, 1.0, [1.0], {"is-preferred": True})], {}),
        ],
        [(0, 0, 1.25, 0, True, [("DP-1", "SAM", "Odyssey", "S1")], {}),
         (2048, 0, 1.0, 3, False, [("HDMI-1", "AOC", "24G2", "S2")], {})],
        {"layout-mode": 1},
    )

    def test_parse(self):
        outs = by_name(gnome.parse_state(self.STATE))
        dp, hd, edp = outs["DP-1"], outs["HDMI-1"], outs["eDP-1"]
        self.assertTrue(dp.primary and dp.vrr_supported and dp.hdr_supported)
        self.assertFalse(dp.vrr)
        self.assertEqual(len(dp.modes), 2)
        self.assertEqual(dp.logical_size(), (2048, 1152))
        self.assertEqual(hd.rotation, 90)
        self.assertFalse(edp.enabled)

    def test_build_config(self):
        outs = by_name(gnome.parse_state(self.STATE))
        dp, hd, edp = outs["DP-1"], outs["HDMI-1"], outs["eDP-1"]
        dp.vrr, dp.hdr = True, True
        edp.enabled, edp.mirror_of = True, "HDMI-1"
        cfg = gnome.build_config([dp, hd, edp])
        self.assertEqual(cfg[0], (0, 0, 1.25, 0, True, [("DP-1", "2560x1440@165-vrr", {"color-mode": 1})]))
        self.assertEqual(cfg[1][3], 3)
        self.assertEqual([s[0] for s in cfg[1][5]], ["HDMI-1", "eDP-1"])


class ModelTest(unittest.TestCase):
    def test_find_mode_and_resolutions(self):
        o = Output("X", modes=[Mode(1920, 1080, 60), Mode(1920, 1080, 144), Mode(2560, 1440, 60)],
                   width=1920, height=1080, refresh=143.9)
        self.assertEqual(o.find_mode().refresh, 144)
        self.assertEqual(o.resolutions(), [(2560, 1440), (1920, 1080)])


if __name__ == "__main__":
    unittest.main()
