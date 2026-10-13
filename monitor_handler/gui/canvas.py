"""Drag-and-drop preview of the monitor layout."""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo, Gtk  # noqa: E402

from .. import layout  # noqa: E402
from ..model import Output  # noqa: E402

PAD = 24
SNAP_PX = 18  # screen pixels


class LayoutCanvas(Gtk.DrawingArea):
    def __init__(self, on_select, on_moved):
        super().__init__()
        self.outputs: list[Output] = []
        self.selected: str | None = None
        self._on_select = on_select
        self._on_moved = on_moved
        self._drag: dict | None = None
        self._frozen: tuple[float, float, float] | None = None  # factor, ox, oy during drags
        self.set_content_height(260)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)

    def set_outputs(self, outputs: list[Output], selected: str | None):
        self.outputs = outputs
        self.selected = selected
        self.queue_draw()

    # ---- geometry ------------------------------------------------------
    def _visible(self) -> list[Output]:
        return [o for o in self.outputs if o.enabled and not o.mirror_of]

    def _transform(self) -> tuple[float, float, float]:
        if self._frozen:
            return self._frozen
        vis = self._visible()
        w, h = self.get_width(), self.get_height()
        if not vis or w <= 2 * PAD or h <= 2 * PAD:
            return (0.05, PAD, PAD)
        min_x = min(o.x for o in vis)
        min_y = min(o.y for o in vis)
        max_x = max(o.x + o.logical_size()[0] for o in vis)
        max_y = max(o.y + o.logical_size()[1] for o in vis)
        bw, bh = max(max_x - min_x, 1), max(max_y - min_y, 1)
        factor = min((w - 2 * PAD) / bw, (h - 2 * PAD) / bh)
        ox = (w - bw * factor) / 2 - min_x * factor
        oy = (h - bh * factor) / 2 - min_y * factor
        return (factor, ox, oy)

    def _screen_rect(self, o: Output) -> tuple[float, float, float, float]:
        f, ox, oy = self._transform()
        x, y, w, h = o.rect()
        return (ox + x * f, oy + y * f, w * f, h * f)

    def _hit(self, px: float, py: float) -> Output | None:
        for o in reversed(self._visible()):
            x, y, w, h = self._screen_rect(o)
            if x <= px <= x + w and y <= py <= y + h:
                return o
        return None

    # ---- drag ----------------------------------------------------------
    def _drag_begin(self, gesture, px, py):
        o = self._hit(px, py)
        if o is None:
            self._drag = None
            return
        self._frozen = self._transform()
        self._drag = {"out": o, "x": o.x, "y": o.y}
        self.selected = o.name
        self._on_select(o.name)

    def _drag_update(self, gesture, dx, dy):
        if not self._drag:
            return
        f = self._frozen[0]
        o = self._drag["out"]
        o.x = self._drag["x"] + round(dx / f)
        o.y = self._drag["y"] + round(dy / f)
        layout.snap(o, self.outputs, round(SNAP_PX / f))
        self.queue_draw()

    def _drag_end(self, gesture, dx, dy):
        if not self._drag:
            return
        moved = self._drag["out"].x != self._drag["x"] or self._drag["out"].y != self._drag["y"]
        self._drag = None
        self._frozen = None
        if moved:
            self._on_moved()
        self.queue_draw()

    # ---- drawing -------------------------------------------------------
    def _draw(self, area, cr, width, height):
        fg = self.get_color()
        vis = self._visible()
        if not vis:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
            _text(cr, self, "Nenhum monitor ligado", 0, 0, width, height, 12)
            return
        mirrors: dict[str, list[str]] = {}
        for o in self.outputs:
            if o.enabled and o.mirror_of:
                mirrors.setdefault(o.mirror_of, []).append(o.name)

        for o in vis:
            x, y, w, h = self._screen_rect(o)
            x, y, w, h = x + 2, y + 2, w - 4, h - 4
            sel = o.name == self.selected
            _rounded(cr, x, y, w, h, 6)
            if sel:
                cr.set_source_rgba(0.21, 0.52, 0.89, 0.85)
            else:
                cr.set_source_rgba(0.5, 0.5, 0.55, 0.35)
            cr.fill_preserve()
            cr.set_line_width(2 if sel else 1)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.8 if sel else 0.4)
            cr.stroke()

            lines = [f"<b>{o.name}</b>", f"{o.width}x{o.height} @ {o.refresh:.0f} Hz"]
            if o.primary:
                lines.append("★ principal")
            if o.rotation:
                lines.append(f"↻ {o.rotation}°")
            if o.name in mirrors:
                lines.append("= " + ", ".join(mirrors[o.name]))
            if sel:
                cr.set_source_rgba(1, 1, 1, 1)
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            size = max(7.0, min(11.0, h / 8, w / 14))
            _text(cr, self, "\n".join(lines), x, y, w, h, size)


def _text(cr, widget, markup, x, y, w, h, size):
    lay = PangoCairo.create_layout(cr)
    font = widget.get_pango_context().get_font_description().copy()
    font.set_size(int(size * Pango.SCALE))
    lay.set_font_description(font)
    lay.set_alignment(Pango.Alignment.CENTER)
    lay.set_width(int(max(w - 8, 1) * Pango.SCALE))
    lay.set_ellipsize(Pango.EllipsizeMode.END)
    lay.set_markup(markup, -1)
    _, ext = lay.get_pixel_extents()
    cr.move_to(x + 4, y + (h - ext.height) / 2)
    PangoCairo.show_layout(cr, lay)


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
