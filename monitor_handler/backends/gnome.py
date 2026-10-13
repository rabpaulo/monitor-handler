"""GNOME backend: talks to Mutter's org.gnome.Mutter.DisplayConfig D-Bus API.
Works on GNOME Wayland and GNOME X11."""

from __future__ import annotations

import json
import os

from ..model import FEAT_HDR, FEAT_MIRROR, FEAT_PRIMARY, FEAT_SCALE, FEAT_VRR, Mode, Output
from .base import Backend, BackendError

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJ_PATH = "/org/gnome/Mutter/DisplayConfig"

# Mutter follows wl_output: transform 1 ("90") is counter-clockwise.
ROT_TO_MUTTER = {0: 0, 90: 3, 180: 2, 270: 1}
MUTTER_TO_ROT = {v: k for k, v in ROT_TO_MUTTER.items()}
LAYOUT_LOGICAL = 1
METHOD_PERSISTENT = 2
COLOR_MODE_DEFAULT = 0
COLOR_MODE_BT2100 = 1


def parse_state(state) -> list[Output]:
    """`state` is the unpacked reply of GetCurrentState()."""
    serial, monitors, logical_monitors, props = state
    layout_scaled = props.get("layout-mode", LAYOUT_LOGICAL) == LAYOUT_LOGICAL
    # connector -> (logical monitor, index of the first connector in it)
    placement = {}
    for lm in logical_monitors:
        x, y, scale, transform, primary, specs, _lm_props = lm
        for i, spec in enumerate(specs):
            placement[spec[0]] = (lm, specs[0][0] if i else None)

    outputs = []
    for (connector, vendor, product, mserial), modes, mprops in monitors:
        o = Output(name=connector, layout_scaled=layout_scaled)
        o.description = mprops.get("display-name") or " ".join(p for p in (vendor, product) if p)
        vrr_modes = {}
        cur_mode = None
        for mode_id, w, h, refresh, pref_scale, scales, mode_props in modes:
            if mode_props.get("is-interlaced"):
                continue
            variable = mode_props.get("refresh-rate-mode") == "variable"
            key = f"{w}x{h}@{refresh:.3f}"
            if variable:
                vrr_modes[key] = mode_id
            else:
                o.modes.append(Mode(w, h, refresh, preferred=bool(mode_props.get("is-preferred")), id=mode_id))
            o.extra.setdefault("scales", {})[mode_id] = list(scales)
            if mode_props.get("is-current"):
                cur_mode = (w, h, refresh, variable, list(scales))
        o.extra["vrr_modes"] = vrr_modes
        o.vrr_supported = bool(vrr_modes)
        if cur_mode:
            o.width, o.height, o.refresh, o.vrr, o.scale_options = cur_mode
        elif o.modes:
            pref = o.preferred_mode()
            o.width, o.height, o.refresh = pref.width, pref.height, pref.refresh
            o.scale_options = o.extra["scales"].get(pref.id, [])
        color_modes = list(mprops.get("supported-color-modes", []))
        o.hdr_supported = COLOR_MODE_BT2100 in color_modes
        o.hdr = mprops.get("color-mode") == COLOR_MODE_BT2100

        if connector in placement:
            lm, mirror_of = placement[connector]
            x, y, scale, transform, primary, _specs, _ = lm
            o.enabled = True
            o.x, o.y, o.scale = x, y, scale
            o.rotation = MUTTER_TO_ROT.get(transform % 4, 0)
            o.primary = bool(primary)
            o.mirror_of = mirror_of
        else:
            o.enabled = False
        outputs.append(o)
    return outputs


def _mode_id(o: Output) -> str:
    if o.vrr:
        variable = o.extra.get("vrr_modes", {})
        best = None
        for key, mode_id in variable.items():
            res, rate = key.split("@")
            if res == f"{o.width}x{o.height}":
                diff = abs(float(rate) - o.refresh)
                if best is None or diff < best[0]:
                    best = (diff, mode_id)
        if best:
            return best[1]
    mode = o.find_mode()
    if mode is None:
        raise BackendError(f"{o.name}: modo {o.width}x{o.height} indisponível")
    return mode.id


def _closest_scale(o: Output, mode_id: str) -> float:
    scales = o.extra.get("scales", {}).get(mode_id) or [1.0]
    return min(scales, key=lambda s: abs(s - o.scale))


def build_config(outputs: list[Output]) -> list[tuple]:
    """Logical monitor list in ApplyMonitorsConfig format: a(iiduba(ssa{sv}))."""
    groups: dict[str, list[Output]] = {}
    for o in outputs:
        if o.enabled and not o.mirror_of:
            groups[o.name] = [o]
    for o in outputs:
        if o.enabled and o.mirror_of in groups:
            groups[o.mirror_of].append(o)
    config = []
    for leader_name, members in groups.items():
        leader = members[0]
        specs = []
        for m in members:
            props = {}
            if m.hdr_supported:
                props["color-mode"] = COLOR_MODE_BT2100 if m.hdr else COLOR_MODE_DEFAULT
            specs.append((m.name, _mode_id(m), props))
        scale = _closest_scale(leader, specs[0][1])
        config.append((leader.x, leader.y, scale, ROT_TO_MUTTER.get(leader.rotation, 0),
                       leader.primary, specs))
    return config


class GnomeBackend(Backend):
    id = "gnome"
    name = "GNOME (Mutter D-Bus)"
    features = frozenset({FEAT_PRIMARY, FEAT_SCALE, FEAT_MIRROR, FEAT_VRR, FEAT_HDR})
    self_confirming = True  # GNOME shows its own "Keep changes?" dialog

    def __init__(self):
        self._serial = 0
        self._layout_mode = None

    @staticmethod
    def _proxy():
        from gi.repository import Gio
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, BUS_NAME, OBJ_PATH, BUS_NAME, None)

    @classmethod
    def available(cls) -> bool:
        if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return False
        try:
            return cls._proxy().get_name_owner() is not None
        except Exception:
            return False

    def list_outputs(self) -> list[Output]:
        try:
            state = self._proxy().call_sync("GetCurrentState", None, 0, -1, None).unpack()
        except Exception as e:
            raise BackendError(f"Falha ao ler o estado do Mutter: {e}") from e
        self._serial = state[0]
        self._layout_mode = state[3].get("layout-mode")
        return parse_state(state)

    def _variant(self, outputs: list[Output]):
        from gi.repository import GLib
        props = {}
        if self._layout_mode is not None:
            props["layout-mode"] = GLib.Variant("u", self._layout_mode)
        lms = []
        for x, y, scale, transform, primary, specs in build_config(outputs):
            vspecs = []
            for name, mode_id, mprops in specs:
                vspecs.append((name, mode_id, {k: GLib.Variant("u", v) for k, v in mprops.items()}))
            lms.append((x, y, scale, transform, primary, vspecs))
        return GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (self._serial, METHOD_PERSISTENT, lms, props))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        return []

    def apply(self, outputs: list[Output]) -> None:
        try:
            self._proxy().call_sync("ApplyMonitorsConfig", self._variant(outputs), 0, -1, None)
        except Exception as e:
            raise BackendError(f"O GNOME recusou a configuração: {e}") from e

    def preview(self, outputs: list[Output]) -> str:
        return "ApplyMonitorsConfig (D-Bus)\n" + json.dumps(build_config(outputs), indent=2)

    def script(self, outputs: list[Output]) -> str:
        return "# O GNOME salva a configuração em ~/.config/monitors.xml automaticamente.\n"

    def persist_hint(self) -> str:
        return "O GNOME salva a configuração automaticamente (~/.config/monitors.xml)."
