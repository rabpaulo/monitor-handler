"""Hyprland backend (hyprctl)."""

from __future__ import annotations

import json
import os
import re

from ..model import FEAT_BIT_DEPTH, FEAT_HDR, FEAT_MIRROR, FEAT_SCALE, FEAT_VRR, Mode, Output
from .base import Backend, have, run

ROT_TO_HYPR = {0: 0, 90: 1, 180: 2, 270: 3}
HYPR_TO_ROT = {v: k for k, v in ROT_TO_HYPR.items()}
MODE_RE = re.compile(r"(\d+)x(\d+)@([\d.]+)Hz")


def parse_monitors(text: str) -> list[Output]:
    outputs = []
    for d in json.loads(text):
        o = Output(name=d["name"])
        o.description = " ".join(p for p in (d.get("make"), d.get("model")) if p) or d.get("description", "")
        o.enabled = not d.get("disabled", False)
        for s in d.get("availableModes", []):
            m = MODE_RE.match(s)
            if m:
                o.modes.append(Mode(int(m[1]), int(m[2]), float(m[3])))
        if o.modes:
            o.modes[0].preferred = True
        o.width, o.height, o.refresh = int(d.get("width", 0)), int(d.get("height", 0)), float(d.get("refreshRate", 0))
        if (not o.width or not o.enabled) and o.modes:
            o.width, o.height, o.refresh = o.modes[0].width, o.modes[0].height, o.modes[0].refresh
        o.x, o.y = int(d.get("x", 0)), int(d.get("y", 0))
        o.rotation = HYPR_TO_ROT.get(int(d.get("transform", 0)) % 4, 0)
        o.scale = float(d.get("scale", 1.0))
        o.vrr_supported = True
        o.vrr = bool(d.get("vrr", False))
        o.hdr_supported = True
        o.hdr = str(d.get("colorManagementPreset", "")).lower().startswith("hdr")
        o.bit_depth_options = [8, 10]
        o.bit_depth = 10 if "2101010" in str(d.get("currentFormat", "")) else 8
        mirror = d.get("mirrorOf")
        o.mirror_of = None if mirror in (None, "", "none") else mirror
        outputs.append(o)
    return outputs


def monitor_rule(o: Output) -> str:
    if not o.enabled:
        return f"{o.name},disable"
    parts = [o.name, f"{o.width}x{o.height}@{o.refresh:.2f}", f"{o.x}x{o.y}", f"{o.scale:g}",
             "transform", str(ROT_TO_HYPR.get(o.rotation, 0)),
             "vrr", "1" if o.vrr else "0"]
    if o.bit_depth == 10:
        parts += ["bitdepth", "10"]
    if o.hdr:
        parts += ["cm", "hdr"]
    if o.mirror_of:
        parts += ["mirror", o.mirror_of]
    return ",".join(parts)


class HyprlandBackend(Backend):
    id = "hyprland"
    name = "Wayland (Hyprland)"
    features = frozenset({FEAT_SCALE, FEAT_VRR, FEAT_HDR, FEAT_BIT_DEPTH, FEAT_MIRROR})

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and have("hyprctl")

    def list_outputs(self) -> list[Output]:
        return parse_monitors(run(["hyprctl", "-j", "monitors", "all"]))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        ordered = sorted(outputs, key=lambda o: not o.enabled)
        batch = " ; ".join(f"keyword monitor {monitor_rule(o)}" for o in ordered)
        return [["hyprctl", "--batch", batch]]

    def script(self, outputs: list[Output]) -> str:
        lines = ["# Monitor Handler — cole no ~/.config/hypr/hyprland.conf"]
        lines += [f"monitor = {monitor_rule(o)}" for o in outputs]
        return "\n".join(lines) + "\n"

    def persist_hint(self) -> str:
        return "Para manter a configuração, adicione as linhas abaixo ao hyprland.conf:"
