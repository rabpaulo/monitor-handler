"""Generic Wayland backend for wlroots-based compositors (river, labwc, wayfire,
niri, ...) using wlr-randr and the wlr-output-management protocol."""

from __future__ import annotations

import json
import os

from ..model import FEAT_SCALE, FEAT_VRR, Mode, Output
from .base import Backend, have, run

ROT_TO_WL = {0: "normal", 90: "90", 180: "180", 270: "270"}
WL_TO_ROT = {v: k for k, v in ROT_TO_WL.items()}


def parse_json(text: str) -> list[Output]:
    outputs = []
    for d in json.loads(text):
        o = Output(name=d["name"])
        o.description = d.get("description") or " ".join(
            p for p in (d.get("make"), d.get("model")) if p and p != "Unknown")
        o.enabled = bool(d.get("enabled", True))
        for m in d.get("modes", []):
            mode = Mode(m["width"], m["height"], float(m["refresh"]), preferred=bool(m.get("preferred")))
            o.modes.append(mode)
            if m.get("current"):
                o.width, o.height, o.refresh = mode.width, mode.height, mode.refresh
        if not o.width and o.modes:
            pref = o.preferred_mode()
            o.width, o.height, o.refresh = pref.width, pref.height, pref.refresh
        pos = d.get("position") or {}
        o.x, o.y = int(pos.get("x", 0)), int(pos.get("y", 0))
        o.rotation = WL_TO_ROT.get(d.get("transform", "normal"), 0)
        o.scale = float(d.get("scale", 1.0))
        if "adaptive_sync" in d:
            o.vrr_supported = True
            o.vrr = bool(d["adaptive_sync"])
        outputs.append(o)
    return outputs


class WlrRandrBackend(Backend):
    id = "wlr-randr"
    name = "Wayland (wlroots / wlr-randr)"
    features = frozenset({FEAT_SCALE, FEAT_VRR})

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY")) and have("wlr-randr")

    def list_outputs(self) -> list[Output]:
        return parse_json(run(["wlr-randr", "--json"]))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        cmd = ["wlr-randr"]
        for o in outputs:
            cmd += ["--output", o.name]
            if not o.enabled:
                cmd.append("--off")
                continue
            cmd += ["--on", "--mode", f"{o.width}x{o.height}@{o.refresh:.3f}Hz",
                    "--pos", f"{o.x},{o.y}",
                    "--transform", ROT_TO_WL.get(o.rotation, "normal"),
                    "--scale", f"{o.scale:g}"]
            if o.vrr_supported:
                cmd += ["--adaptive-sync", "enabled" if o.vrr else "disabled"]
        return [cmd]

    def persist_hint(self) -> str:
        return ("Para manter a configuração, execute o comando abaixo no autostart do seu "
                "compositor ou use o kanshi:")
