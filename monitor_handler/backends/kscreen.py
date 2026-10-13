"""KDE Plasma backend (kscreen-doctor). Works on Plasma Wayland and X11."""

from __future__ import annotations

import json
import os

from ..model import FEAT_HDR, FEAT_PRIMARY, FEAT_RGB_RANGE, FEAT_SCALE, FEAT_VRR, Mode, Output
from .base import Backend, have, run

# KScreen::Output::Rotation
ROT_TO_KDE = {0: "normal", 90: "right", 180: "inverted", 270: "left"}
KDE_ROT_ENUM = {1: 0, 2: 270, 4: 180, 8: 90}
# KScreen::Output::Capability
CAP_VRR = 0x2
CAP_RGB_RANGE = 0x4
CAP_HDR = 0x8
CAP_WCG = 0x10
RGB_RANGES = ["Automatic", "Full", "Limited"]
VRR_POLICY = {0: False, 1: True, 2: True}


def parse_json(text: str) -> list[Output]:
    data = json.loads(text)
    outputs = []
    for d in data.get("outputs", []):
        if not d.get("connected", True):
            continue
        o = Output(name=d["name"])
        o.description = " ".join(p for p in (d.get("manufacturer"), d.get("model")) if p) or d.get("type", "")
        o.enabled = bool(d.get("enabled"))
        preferred = set(map(str, d.get("preferredModes", [])))
        cur_id = str(d.get("currentModeId", ""))
        for m in d.get("modes", []):
            size = m.get("size", {})
            mode = Mode(size.get("width", 0), size.get("height", 0), float(m.get("refreshRate", 0)),
                        preferred=str(m["id"]) in preferred, id=str(m["id"]))
            o.modes.append(mode)
            if mode.id == cur_id:
                o.width, o.height, o.refresh = mode.width, mode.height, mode.refresh
        if not o.width and o.modes:
            pref = o.preferred_mode()
            o.width, o.height, o.refresh = pref.width, pref.height, pref.refresh
        pos = d.get("pos", {})
        o.x, o.y = int(pos.get("x", 0)), int(pos.get("y", 0))
        o.rotation = KDE_ROT_ENUM.get(int(d.get("rotation", 1)), 0)
        o.scale = float(d.get("scale", 1.0))
        o.primary = d.get("priority") == 1
        caps = int(d.get("capabilities", 0))
        o.vrr_supported = bool(caps & CAP_VRR)
        o.vrr = VRR_POLICY.get(int(d.get("vrrPolicy", 0)), False)
        o.hdr_supported = bool(caps & CAP_HDR)
        o.hdr = bool(d.get("hdr", False))
        o.extra["wcg_supported"] = bool(caps & CAP_WCG)
        if caps & CAP_RGB_RANGE:
            o.rgb_range_options = list(RGB_RANGES)
            o.rgb_range = RGB_RANGES[int(d.get("rgbRange", 0))] if int(d.get("rgbRange", 0)) < 3 else "Automatic"
        outputs.append(o)
    return outputs


def output_args(o: Output) -> list[str]:
    p = f"output.{o.name}."
    if not o.enabled:
        return [p + "disable"]
    mode = o.find_mode()
    args = [p + "enable",
            p + "mode." + (mode.id if mode and mode.id else f"{o.width}x{o.height}@{round(o.refresh)}"),
            p + f"position.{o.x},{o.y}",
            p + f"scale.{o.scale:g}",
            p + "rotation." + ROT_TO_KDE.get(o.rotation, "normal")]
    if o.primary:
        args.append(p + "priority.1")
    if o.vrr_supported:
        args.append(p + "vrrpolicy." + ("automatic" if o.vrr else "never"))
    if o.hdr_supported:
        state = "enable" if o.hdr else "disable"
        args.append(p + "hdr." + state)
        if o.extra.get("wcg_supported"):
            args.append(p + "wcg." + state)
    if o.rgb_range and o.rgb_range_options:
        args.append(p + "rgbrange." + o.rgb_range.lower())
    return args


class KScreenBackend(Backend):
    id = "kscreen"
    name = "KDE Plasma (kscreen-doctor)"
    features = frozenset({FEAT_PRIMARY, FEAT_SCALE, FEAT_VRR, FEAT_HDR, FEAT_RGB_RANGE})

    @classmethod
    def available(cls) -> bool:
        return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and have("kscreen-doctor")

    def list_outputs(self) -> list[Output]:
        return parse_json(run(["kscreen-doctor", "-j"]))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        ordered = sorted(outputs, key=lambda o: not o.enabled)
        cmd = ["kscreen-doctor"]
        for o in ordered:
            cmd += output_args(o)
        return [cmd]

    def persist_hint(self) -> str:
        return "O KDE salva a configuração automaticamente. O comando equivalente é:"
