import unittest

from monitor_handler import layout
from monitor_handler.model import Output


def mon(name, w, h, x=0, y=0, **kw):
    return Output(name, width=w, height=h, x=x, y=y, **kw)


class LayoutTest(unittest.TestCase):
    def test_place_each_side(self):
        a = mon("A", 2560, 1440)
        b = mon("B", 1920, 1080)
        layout.place_relative(b, a, "right")
        self.assertEqual((b.x, b.y), (2560, 0))
        layout.place_relative(b, a, "left", "end")
        self.assertEqual((b.x, b.y), (-1920, 360))
        layout.place_relative(b, a, "above", "center")
        self.assertEqual((b.x, b.y), (320, -1080))
        layout.place_relative(b, a, "below")
        self.assertEqual((b.x, b.y), (0, 1440))
        self.assertEqual(layout.relation(b, a), ("below", "start"))

    def test_vertical_monitor(self):
        a = mon("A", 2560, 1440)
        b = mon("B", 1920, 1080, rotation=90)
        layout.place_relative(b, a, "right", "center")
        self.assertEqual(b.logical_size(), (1080, 1920))
        self.assertEqual((b.x, b.y), (2560, -240))
        self.assertEqual(layout.relation(b, a), ("right", "center"))

    def test_normalize_and_mirror(self):
        a = mon("A", 1920, 1080)
        b = mon("B", 1920, 1080)
        layout.place_relative(b, a, "left")
        layout.normalize([a, b])
        self.assertEqual((b.x, a.x), (0, 1920))
        layout.place_relative(b, a, "mirror")
        layout.normalize([a, b])
        self.assertEqual((b.x, b.y, b.mirror_of), (0, 0, "A"))
        self.assertEqual(layout.validate([a, b]), [])

    def test_validate_overlap(self):
        a = mon("A", 1920, 1080)
        b = mon("B", 1920, 1080, x=100)
        self.assertTrue(layout.validate([a, b]))
        a.enabled = b.enabled = False
        self.assertTrue(layout.validate([a, b]))

    def test_snap(self):
        a = mon("A", 1920, 1080)
        b = mon("B", 1920, 1080, x=1930, y=12)
        layout.snap(b, [a, b], 20)
        self.assertEqual((b.x, b.y), (1920, 0))

    def test_scaled_size(self):
        a = mon("A", 3840, 2160, scale=2.0)
        self.assertEqual(a.logical_size(), (1920, 1080))
        a.layout_scaled = False
        self.assertEqual(a.logical_size(), (3840, 2160))


if __name__ == "__main__":
    unittest.main()
