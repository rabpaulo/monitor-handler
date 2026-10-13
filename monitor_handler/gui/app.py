"""Main GTK 4 window."""

from __future__ import annotations

import os
import shlex
import stat
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import __version__, layout  # noqa: E402
from ..backends import Backend, BackendError  # noqa: E402
from ..backends.xrandr import build_command as xrandr_command  # noqa: E402
from ..model import (  # noqa: E402
    FEAT_BIT_DEPTH, FEAT_BRIGHTNESS, FEAT_HDR, FEAT_MIRROR, FEAT_PRIMARY, FEAT_RGB_RANGE,
    FEAT_SCALE, FEAT_VRR, ROTATIONS, Output, clone_all,
)
from .canvas import LayoutCanvas  # noqa: E402

APP_ID = "io.github.rabpaulo.MonitorHandler"
CONFIRM_SECONDS = 15
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "monitor-handler"

ROTATION_LABELS = {
    0: "Paisagem (normal)",
    90: "Retrato (girado 90° à direita)",
    180: "Paisagem invertida (180°)",
    270: "Retrato (girado 90° à esquerda)",
}
SIDE_LABELS = {
    "right": "À direita de",
    "left": "À esquerda de",
    "above": "Acima de",
    "below": "Abaixo de",
    "mirror": "Espelhar (duplicar)",
    "custom": "Posição personalizada",
}
ALIGN_LABELS = {"start": "Início (topo/esquerda)", "center": "Centro", "end": "Fim (base/direita)"}
DEFAULT_SCALES = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


class Choice:
    """Gtk.DropDown that maps visible labels to Python values."""

    def __init__(self, on_change):
        self.widget = Gtk.DropDown.new_from_strings([])
        self.widget.set_hexpand(True)
        self.values: list = []
        self._labels: list[str] = []
        self._on_change = on_change
        self._muted = False
        self.widget.connect("notify::selected", self._changed)

    def set(self, items: list[tuple[str, object]], current):
        self._muted = True
        labels = [label for label, _ in items]
        self.values = [v for _, v in items]
        if labels != self._labels:
            self._labels = labels
            self.widget.set_model(Gtk.StringList.new(labels))
        idx = self._index(current)
        self.widget.set_selected(idx if idx is not None else Gtk.INVALID_LIST_POSITION)
        self._muted = False

    def _index(self, value):
        for i, v in enumerate(self.values):
            if v == value or (isinstance(v, float) and isinstance(value, (int, float)) and abs(v - value) < 0.005):
                return i
        return None

    def get(self):
        i = self.widget.get_selected()
        return self.values[i] if 0 <= i < len(self.values) else None

    def _changed(self, *_):
        if self._muted:
            return
        value = self.get()
        # Handlers may rebuild this very dropdown; doing that inside its own
        # notify::selected emission can lock GTK up, so run them afterwards.
        GLib.idle_add(lambda: self._on_change(value) and False)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, backend: Backend, dry_run: bool):
        super().__init__(application=app, title="Monitor Handler")
        self.backend = backend
        self.dry_run = dry_run
        self.saved: list[Output] = []      # state as read from the system
        self.outputs: list[Output] = []    # state being edited
        self.selected: str | None = None
        self._loading = False
        self.set_default_size(880, 760)

        header = Gtk.HeaderBar()
        title = Gtk.Label(label=f"Monitor Handler — {backend.name}" + (" (simulação)" if dry_run else ""))
        title.add_css_class("title")
        header.set_title_widget(title)
        reload_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Detectar monitores novamente")
        reload_btn.connect("clicked", lambda *_: self.reload())
        header.pack_start(reload_btn)
        about_btn = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="Sobre")
        about_btn.connect("clicked", self._about)
        header.pack_end(about_btn)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{side}")(12)
        self.set_child(root)

        hint = Gtk.Label(label="Arraste os monitores para posicioná-los. Clique para selecionar.", xalign=0)
        hint.add_css_class("dim-label")
        root.append(hint)
        frame = Gtk.Frame()
        self.canvas = LayoutCanvas(self._select, self._canvas_moved)
        frame.set_child(self.canvas)
        root.append(frame)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        root.append(scroller)
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=8, halign=Gtk.Align.CENTER)
        self.grid.set_size_request(620, -1)
        self.grid.set_margin_top(6)
        scroller.set_child(self.grid)
        self._build_controls()

        root.append(self._build_xrandr_box())

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("error")
        root.append(self.status)

        bar = Gtk.Box(spacing=8)
        root.append(bar)
        reset = Gtk.Button(label="Desfazer alterações")
        reset.connect("clicked", lambda *_: self._reset())
        bar.append(reset)
        cmds = Gtk.Button(label="Ver comandos")
        cmds.connect("clicked", lambda *_: self._show_commands())
        bar.append(cmds)
        persist = Gtk.Button(label="Salvar para o login")
        persist.connect("clicked", lambda *_: self._persist())
        bar.append(persist)
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        self.apply_btn = Gtk.Button(label="Aplicar")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self._apply())
        bar.append(self.apply_btn)

        self.reload()

    # ---- controls ------------------------------------------------------
    def _row(self, label: str, widget: Gtk.Widget, feature: str | None = None) -> tuple:
        lbl = Gtk.Label(label=label, xalign=1)
        r = self._next_row
        self.grid.attach(lbl, 0, r, 1, 1)
        self.grid.attach(widget, 1, r, 1, 1)
        self._next_row += 1
        if feature and not self.backend.supports(feature):
            lbl.set_visible(False)
            widget.set_visible(False)
        return (lbl, widget)

    def _build_controls(self):
        self._next_row = 0
        self.c_monitor = Choice(self._select)
        self._row("Monitor", self.c_monitor.widget)

        self.info = Gtk.Label(xalign=0, selectable=True)
        self.info.add_css_class("dim-label")
        self._row("", self.info)

        toggles = Gtk.Box(spacing=18)
        self.sw_enabled = Gtk.CheckButton(label="Ligado")
        self.sw_enabled.connect("toggled", self._on_enabled)
        toggles.append(self.sw_enabled)
        self.chk_primary = Gtk.CheckButton(label="Monitor principal")
        self.chk_primary.connect("toggled", self._on_primary)
        self.chk_primary.set_visible(self.backend.supports(FEAT_PRIMARY))
        toggles.append(self.chk_primary)
        self._row("", toggles)

        self.c_res = Choice(self._on_resolution)
        self._row("Resolução", self.c_res.widget)
        self.c_rate = Choice(self._on_rate)
        self._row("Taxa de atualização", self.c_rate.widget)
        self.c_rot = Choice(self._on_rotation)
        self._row("Orientação", self.c_rot.widget)
        self.c_scale = Choice(self._on_scale)
        self._row("Escala", self.c_scale.widget, FEAT_SCALE)

        self.grid.attach(Gtk.Separator(), 0, self._next_row, 2, 1)
        self._next_row += 1
        self.c_side = Choice(self._on_relation)
        self.row_side = self._row("Posição", self.c_side.widget)
        self.c_ref = Choice(self._on_relation)
        self.row_ref = self._row("Em relação a", self.c_ref.widget)
        self.c_align = Choice(self._on_relation)
        self.row_align = self._row("Alinhamento", self.c_align.widget)
        pos = Gtk.Box(spacing=6)
        self.sp_x = Gtk.SpinButton.new_with_range(-32768, 32768, 1)
        self.sp_y = Gtk.SpinButton.new_with_range(-32768, 32768, 1)
        self.sp_x.connect("value-changed", self._on_xy)
        self.sp_y.connect("value-changed", self._on_xy)
        pos.append(Gtk.Label(label="X"))
        pos.append(self.sp_x)
        pos.append(Gtk.Label(label="Y"))
        pos.append(self.sp_y)
        self._row("Coordenadas", pos)

        self.grid.attach(Gtk.Separator(), 0, self._next_row, 2, 1)
        self._next_row += 1
        self.chk_vrr = Gtk.CheckButton(label="Taxa de atualização variável (VRR / FreeSync / G-Sync)")
        self.chk_vrr.connect("toggled", self._on_vrr)
        self.row_vrr = self._row("VRR", self.chk_vrr, FEAT_VRR)
        self.chk_hdr = Gtk.CheckButton(label="Ativar HDR")
        self.chk_hdr.connect("toggled", self._on_hdr)
        self.row_hdr = self._row("HDR", self.chk_hdr, FEAT_HDR)
        self.c_depth = Choice(self._on_depth)
        self.row_depth = self._row("Profundidade de cor", self.c_depth.widget, FEAT_BIT_DEPTH)
        self.c_rgb = Choice(self._on_rgb)
        self.row_rgb = self._row("Faixa RGB", self.c_rgb.widget, FEAT_RGB_RANGE)
        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 1.5, 0.05)
        self.brightness.add_mark(1.0, Gtk.PositionType.BOTTOM, "100%")
        self.brightness.set_hexpand(True)
        self.brightness.connect("value-changed", self._on_brightness)
        self.row_brightness = self._row("Brilho (gamma)", self.brightness, FEAT_BRIGHTNESS)

    def _build_xrandr_box(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label="<b>Comando xrandr</b>", use_markup=True, xalign=0)
        head.append(title)
        self.xrandr_note = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.xrandr_note.add_css_class("dim-label")
        head.append(self.xrandr_note)
        copy = Gtk.Button(tooltip_text="Copia o comando xrandr equivalente à configuração acima")
        content = Gtk.Box(spacing=6)
        content.append(Gtk.Image(icon_name="edit-copy-symbolic"))
        content.append(Gtk.Label(label="Copiar comando"))
        copy.set_child(content)
        copy.connect("clicked", lambda *_: self._copy(self.xrandr_text))
        head.append(copy)
        box.append(head)
        self.xrandr_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.xrandr_label.set_wrap_mode(Pango.WrapMode.CHAR)
        self.xrandr_label.add_css_class("monospace")
        frame = Gtk.Frame(child=self.xrandr_label)
        self.xrandr_label.set_margin_start(8)
        self.xrandr_label.set_margin_end(8)
        self.xrandr_label.set_margin_top(6)
        self.xrandr_label.set_margin_bottom(6)
        box.append(frame)
        self.xrandr_text = ""
        return box

    def _update_xrandr(self):
        outs = self._final()
        native = self.backend.id == "xrandr"
        self.xrandr_text = shlex.join(xrandr_command(outs, driver_props=native))
        self.xrandr_label.set_label(self.xrandr_text)
        notes = []
        if not native:
            notes.append("só funciona numa sessão X11")
            if any(o.enabled and abs(o.scale - 1.0) > 0.005 for o in outs):
                notes.append("escala não se aplica no X11; as posições usam o tamanho escalado")
        self.xrandr_note.set_label(" · ".join(notes))

    def _copy(self, text: str):
        Gdk.Display.get_default().get_clipboard().set(text)
        self._toast("Comando copiado para a área de transferência")

    def _toast(self, text: str):
        self.status.remove_css_class("error")
        self.status.set_label(text)
        GLib.timeout_add_seconds(3, self._clear_toast)

    def _clear_toast(self):
        self.status.add_css_class("error")
        self._validate()
        return False

    def _show_row(self, row: tuple, visible: bool):
        for w in row:
            w.set_visible(visible)

    # ---- data flow -----------------------------------------------------
    def reload(self):
        try:
            outs = self.backend.list_outputs()
        except BackendError as e:
            self._error("Erro ao detectar monitores", str(e))
            outs = []
        self.saved = outs
        self.outputs = clone_all(outs)
        names = [o.name for o in self.outputs]
        if self.selected not in names:
            prim = next((o for o in self.outputs if o.primary), None)
            self.selected = prim.name if prim else (names[0] if names else None)
        self._refresh()

    def _reset(self):
        self.outputs = clone_all(self.saved)
        self._refresh()

    def _cur(self) -> Output | None:
        return next((o for o in self.outputs if o.name == self.selected), None)

    def _reference_for(self, o: Output) -> Output | None:
        others = [x for x in self.outputs if x is not o and x.enabled and not x.mirror_of]
        if not others:
            return None
        if o.mirror_of:
            return next((x for x in others if x.name == o.mirror_of), others[0])
        for x in others:
            if layout.relation(o, x):
                return x
        return next((x for x in others if x.primary), others[0])

    def _refresh(self):
        """Push model state into every widget."""
        self._loading = True
        try:
            self.c_monitor.set([(self._monitor_label(o), o.name) for o in self.outputs], self.selected)
            o = self._cur()
            self.grid.set_sensitive(o is not None)
            if o is not None:
                self._fill(o)
            self.canvas.set_outputs(self.outputs, self.selected)
            self._validate()
        finally:
            self._loading = False

    def _monitor_label(self, o: Output) -> str:
        text = o.name
        if o.description:
            text += f" — {o.description}"
        if not o.enabled:
            text += " (desligado)"
        return text

    def _fill(self, o: Output):
        info = [f"{len(o.modes)} modos"]
        if o.extra.get("vrr_capable"):
            info.append("monitor com suporte a VRR")
        self.info.set_label(" · ".join(info))
        self.sw_enabled.set_active(o.enabled)
        self.chk_primary.set_active(o.primary)
        self.c_res.widget.set_sensitive(o.enabled)
        self.c_rate.widget.set_sensitive(o.enabled)
        # A mirror follows its source's orientation and scale
        self.c_rot.widget.set_sensitive(o.enabled and not o.mirror_of)
        self.c_scale.widget.set_sensitive(o.enabled and not o.mirror_of)

        self.c_res.set([(f"{w}x{h}" + (" (recomendada)" if self._is_pref(o, w, h) else ""), (w, h))
                        for w, h in o.resolutions()], (o.width, o.height))
        self.c_rate.set([(f"{r:.2f} Hz", r) for r in o.rates_for(o.width, o.height)], o.refresh)
        self.c_rot.set([(ROTATION_LABELS[r], r) for r in ROTATIONS], o.rotation)
        scales = sorted(set(round(s, 4) for s in (o.scale_options or DEFAULT_SCALES)) | {round(o.scale, 4)})
        self.c_scale.set([(f"{s * 100:.0f}%", s) for s in scales], round(o.scale, 4))

        ref = self._reference_for(o)
        has_ref = ref is not None and o.enabled
        for row in (self.row_side, self.row_ref, self.row_align):
            self._show_row(row, has_ref)
        if has_ref:
            others = [x for x in self.outputs if x is not o and x.enabled and not x.mirror_of]
            self.c_ref.set([(x.name, x.name) for x in others], ref.name)
            rel = layout.relation(o, ref)
            sides = ["right", "left", "above", "below"]
            if self.backend.supports(FEAT_MIRROR):
                sides.append("mirror")
            sides.append("custom")
            side, align = rel if rel else ("custom", "start")
            self.c_side.set([(SIDE_LABELS[s], s) for s in sides], side)
            self.c_align.set([(ALIGN_LABELS[a], a) for a in layout.ALIGNS], align)
            self._show_row(self.row_align, side not in ("mirror", "custom"))
        self.sp_x.set_value(o.x)
        self.sp_y.set_value(o.y)
        self.sp_x.set_sensitive(o.enabled and not o.mirror_of)
        self.sp_y.set_sensitive(o.enabled and not o.mirror_of)

        b = self.backend
        self._show_row(self.row_vrr, b.supports(FEAT_VRR) and o.vrr_supported)
        self.chk_vrr.set_active(o.vrr)
        self._show_row(self.row_hdr, b.supports(FEAT_HDR) and o.hdr_supported)
        self.chk_hdr.set_active(o.hdr)
        self._show_row(self.row_depth, b.supports(FEAT_BIT_DEPTH) and bool(o.bit_depth_options))
        depth_items = [(f"{d} bits por canal", d) for d in o.bit_depth_options]
        if o.bit_depth is None:
            depth_items.insert(0, ("Padrão do sistema", None))
        self.c_depth.set(depth_items, o.bit_depth)
        self._show_row(self.row_rgb, b.supports(FEAT_RGB_RANGE) and bool(o.rgb_range_options))
        self.c_rgb.set([(r, r) for r in o.rgb_range_options], o.rgb_range)
        self.brightness.set_value(o.brightness)
        for row in (self.row_vrr, self.row_hdr, self.row_depth, self.row_rgb, self.row_brightness):
            row[1].set_sensitive(o.enabled)

    @staticmethod
    def _is_pref(o: Output, w: int, h: int) -> bool:
        p = o.preferred_mode()
        return bool(p and p.preferred and p.resolution == (w, h))

    def _validate(self):
        problems = layout.validate(self.outputs)
        self.status.set_label("\n".join(problems))
        self.apply_btn.set_sensitive(not problems)
        self._update_xrandr()

    def _changed(self, keep_selection_ui=False):
        self.canvas.set_outputs(self.outputs, self.selected)
        if not keep_selection_ui:
            self._refresh()
        else:
            self._validate()

    def _resize(self, o: Output, mutate):
        """Apply a size-changing edit and keep neighbours attached."""
        others = [x for x in self.outputs if x is not o and x.enabled and not x.mirror_of]
        anchor = next(((x, layout.relation(o, x)) for x in others if layout.relation(o, x)), None)
        attached = [(x, layout.relation(x, o)) for x in others if layout.relation(x, o)]
        mutate()
        if anchor:
            layout.place_relative(o, anchor[0], *anchor[1])
        for x, rel in attached:
            if anchor and x is anchor[0]:
                continue
            layout.place_relative(x, o, *rel)
        layout.normalize(self.outputs)

    # ---- handlers ------------------------------------------------------
    def _select(self, name):
        if self._loading or name is None:
            return
        self.selected = name
        self._refresh()

    def _canvas_moved(self):
        layout.normalize(self.outputs)
        self._refresh()

    def _on_enabled(self, btn):
        o = self._cur()
        if self._loading or not o:
            return
        o.enabled = btn.get_active()
        if o.enabled:
            o.mirror_of = None
            if not o.width and o.modes:
                p = o.preferred_mode()
                o.width, o.height, o.refresh = p.width, p.height, p.refresh
            act = [x for x in self.outputs if x is not o and x.enabled and not x.mirror_of]
            o.x = max((x.x + x.logical_size()[0] for x in act), default=0)
            o.y = 0
        else:
            for x in self.outputs:
                if x.mirror_of == o.name:
                    x.mirror_of = None
            if o.primary:
                o.primary = False
                nxt = next((x for x in self.outputs if x.enabled), None)
                if nxt:
                    nxt.primary = True
        if not any(x.primary for x in self.outputs if x.enabled) and self.backend.supports(FEAT_PRIMARY):
            nxt = next((x for x in self.outputs if x.enabled), None)
            if nxt:
                nxt.primary = True
        layout.normalize(self.outputs)
        self._changed()

    def _on_primary(self, btn):
        o = self._cur()
        if self._loading or not o:
            return
        if btn.get_active():
            for x in self.outputs:
                x.primary = x is o
        else:
            o.primary = False
        self._changed()

    def _on_resolution(self, value):
        o = self._cur()
        if self._loading or not o or value is None:
            return
        w, h = value

        def mutate():
            rates = o.rates_for(w, h)
            o.width, o.height = w, h
            o.refresh = min(rates, key=lambda r: abs(r - o.refresh)) if rates else o.refresh
        self._resize(o, mutate)
        self._changed()

    def _on_rate(self, value):
        o = self._cur()
        if self._loading or not o or value is None:
            return
        o.refresh = value
        self._changed()

    def _on_rotation(self, value):
        o = self._cur()
        if self._loading or not o or value is None:
            return
        self._resize(o, lambda: setattr(o, "rotation", value))
        self._changed()

    def _on_scale(self, value):
        o = self._cur()
        if self._loading or not o or value is None:
            return
        self._resize(o, lambda: setattr(o, "scale", value))
        self._changed()

    def _on_relation(self, _value):
        o = self._cur()
        if self._loading or not o:
            return
        side, ref_name, align = self.c_side.get(), self.c_ref.get(), self.c_align.get() or "start"
        ref = next((x for x in self.outputs if x.name == ref_name), None)
        if side == "custom" or ref is None:
            o.mirror_of = None
            self._changed()
            return
        layout.place_relative(o, ref, side, align)
        layout.normalize(self.outputs)
        self._changed()

    def _on_xy(self, *_):
        o = self._cur()
        if self._loading or not o:
            return
        o.x, o.y = int(self.sp_x.get_value()), int(self.sp_y.get_value())
        self._changed(keep_selection_ui=True)

    def _on_vrr(self, btn):
        o = self._cur()
        if not self._loading and o:
            o.vrr = btn.get_active()

    def _on_hdr(self, btn):
        o = self._cur()
        if self._loading or not o:
            return
        o.hdr = btn.get_active()
        if o.hdr and 10 in o.bit_depth_options and (o.bit_depth or 0) < 10:
            o.bit_depth = 10
        self._refresh()

    def _on_depth(self, value):
        o = self._cur()
        if not self._loading and o:
            o.bit_depth = value
            self._update_xrandr()

    def _on_rgb(self, value):
        o = self._cur()
        if not self._loading and o and value:
            o.rgb_range = value
            self._update_xrandr()

    def _on_brightness(self, scale):
        o = self._cur()
        if not self._loading and o:
            o.brightness = round(scale.get_value(), 2)
            self._update_xrandr()

    # ---- actions -------------------------------------------------------
    def _final(self) -> list[Output]:
        outs = clone_all(self.outputs)
        layout.normalize(outs)
        return outs

    def _apply(self):
        new = self._final()
        problems = layout.validate(new)
        if problems:
            self._error("Configuração inválida", "\n".join(problems))
            return
        if self.dry_run:
            self._text_dialog("Simulação — nada foi alterado", "Comandos que seriam executados:",
                              self.backend.preview(new))
            return
        previous = clone_all(self.saved)
        try:
            self.backend.apply(new)
        except BackendError as e:
            self._error("Não foi possível aplicar", str(e))
            return
        if self.backend.self_confirming:
            GLib.timeout_add(1500, self._reload_once)
            return
        ConfirmDialog(self, lambda keep: self._confirmed(keep, previous))

    def _reload_once(self):
        self.reload()
        return False

    def _confirmed(self, keep: bool, previous: list[Output]):
        if not keep:
            try:
                self.backend.apply(previous)
            except BackendError as e:
                self._error("Falha ao reverter", str(e))
        GLib.timeout_add(800, self._reload_once)

    def _show_commands(self):
        self._text_dialog("Comandos", "Configuração atual em forma de comando:", self.backend.preview(self._final()))

    def _persist(self):
        text = self.backend.script(self._final())
        hint = self.backend.persist_hint()
        if self.backend.commands(self._final()):
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            path = CONFIG_DIR / (f"{self.backend.id}.sh" if text.startswith("#!") else f"{self.backend.id}.conf")
            path.write_text(text)
            if text.startswith("#!"):
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                hint += f"\n\n    {path}\n\nConteúdo salvo:"
            else:
                hint += f"\n(Uma cópia foi salva em {path})"
        self._text_dialog("Salvar para o login", hint, text)

    # ---- dialogs -------------------------------------------------------
    def _error(self, title: str, detail: str):
        dlg = Gtk.AlertDialog(message=title, detail=detail)
        dlg.show(self)

    def _text_dialog(self, title: str, intro: str, text: str):
        win = Gtk.Window(title=title, transient_for=self, modal=True, default_width=640, default_height=360)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(12)
        box.append(Gtk.Label(label=intro, xalign=0, wrap=True, selectable=True))
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        view.get_buffer().set_text(text)
        sw = Gtk.ScrolledWindow(vexpand=True, child=view)
        box.append(sw)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        copy = Gtk.Button(label="Copiar")
        copy.connect("clicked", lambda *_: self._copy(text))
        close = Gtk.Button(label="Fechar")
        close.connect("clicked", lambda *_: win.close())
        btns.append(copy)
        btns.append(close)
        box.append(btns)
        win.set_child(box)
        win.present()

    def _about(self, *_):
        Gtk.AboutDialog(transient_for=self, modal=True, program_name="Monitor Handler", version=__version__,
                        comments="Configure resolução, posição, orientação, taxa de atualização, "
                                 "VRR e HDR dos seus monitores no X11 e no Wayland.",
                        license_type=Gtk.License.MIT_X11,
                        website="https://github.com/rabpaulo/monitor-handler").present()


class ConfirmDialog(Gtk.Window):
    """'Keep these settings?' with automatic revert, like every desktop does."""

    def __init__(self, parent: Gtk.Window, on_done):
        super().__init__(title="Manter configuração?", transient_for=parent, modal=True,
                         deletable=False, resizable=False)
        self._on_done = on_done
        self._left = CONFIRM_SECONDS
        self._finished = False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(18)
        box.append(Gtk.Label(label="<b>Manter as novas configurações de monitor?</b>", use_markup=True))
        self.label = Gtk.Label()
        box.append(self.label)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        revert = Gtk.Button(label="Reverter")
        revert.connect("clicked", lambda *_: self._finish(False))
        keep = Gtk.Button(label="Manter")
        keep.add_css_class("suggested-action")
        keep.connect("clicked", lambda *_: self._finish(True))
        btns.append(revert)
        btns.append(keep)
        box.append(btns)
        self.set_child(box)
        self._tick()
        GLib.timeout_add_seconds(1, self._tick)
        self.present()
        keep.grab_focus()

    def _tick(self):
        if self._finished:
            return False
        if self._left <= 0:
            self._finish(False)
            return False
        self.label.set_label(f"Revertendo automaticamente em {self._left} s…")
        self._left -= 1
        return True

    def _finish(self, keep: bool):
        if self._finished:
            return
        self._finished = True
        self.close()
        self._on_done(keep)


class App(Gtk.Application):
    def __init__(self, backend: Backend, dry_run: bool = False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.backend = backend
        self.dry_run = dry_run

    def do_activate(self):
        MainWindow(self, self.backend, self.dry_run).present()


def run_gui(backend: Backend, dry_run: bool = False) -> int:
    return App(backend, dry_run).run([])
