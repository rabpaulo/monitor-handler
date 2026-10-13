"""Sway backend (swaymsg IPC)."""

from __future__ import annotations

import json
import os
import shlex

from ..model import FEAT_BIT_DEPTH, FEAT_HDR, FEAT_SCALE, FEAT_VRR, Mode, Output
from .base import Backend, have, run

ROT_TO_SWAY = {0: "normal", 90: "90", 180: "180", 270: "270"}
SWAY_TO_ROT = {v: k for k, v in ROT_TO_SWAY.items()}


def parse_outputs(text: str) -> list[Output]:
    outputs = []
    for d in json.loads(text):
        o = Output(name=d["name"])
        o.description = " ".join(p for p in (d.get("make"), d.get("model")) if p and p != "Unknown")
        o.enabled = bool(d.get("active", True))
        for m in d.get("modes", []):
            o.modes.append(Mode(m["width"], m["height"], m["refresh"] / 1000.0))
        cur = d.get("current_mode")
        if cur:
            o.width, o.height, o.refresh = cur["width"], cur["height"], cur["refresh"] / 1000.0
        elif o.modes:
            o.width, o.height, o.refresh = o.modes[0].width, o.modes[0].height, o.modes[0].refresh
        rect = d.get("rect") or {}
        o.x, o.y = int(rect.get("x", 0)), int(rect.get("y", 0))
        o.rotation = SWAY_TO_ROT.get(d.get("transform", "normal"), 0)
        o.scale = float(d.get("scale", 1.0)) if d.get("scale", -1) > 0 else 1.0
        if "adaptive_sync_status" in d:
            o.vrr_supported = True
            o.vrr = d["adaptive_sync_status"] == "enabled"
        if "hdr" in d:  # sway >= 1.11
            o.hdr_supported = True
            o.hdr = bool(d["hdr"])
        o.bit_depth_options = [8, 10]
        outputs.append(o)
    return outputs


def output_args(o: Output) -> list[str]:
    if not o.enabled:
        return ["output", o.name, "disable"]
    args = ["output", o.name, "enable",
            "mode", f"{o.width}x{o.height}@{o.refresh:.3f}Hz",
            "position", str(o.x), str(o.y),
            "scale", f"{o.scale:g}",
            "transform", ROT_TO_SWAY.get(o.rotation, "normal")]
    if o.vrr_supported:
        args += ["adaptive_sync", "on" if o.vrr else "off"]
    if o.bit_depth in (8, 10):
        args += ["render_bit_depth", str(o.bit_depth)]
    if o.hdr_supported:
        args += ["hdr", "on" if o.hdr else "off"]
    return args


class SwayBackend(Backend):
    id = "sway"
    name = "Wayland (Sway)"
    features = frozenset({FEAT_SCALE, FEAT_VRR, FEAT_HDR, FEAT_BIT_DEPTH})

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("SWAYSOCK")) and have("swaymsg")

    def list_outputs(self) -> list[Output]:
        return parse_outputs(run(["swaymsg", "-r", "-t", "get_outputs"]))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        # Disabled outputs last so there is always an active output in between.
        ordered = sorted(outputs, key=lambda o: not o.enabled)
        return [["swaymsg", *output_args(o)] for o in ordered]

    def script(self, outputs: list[Output]) -> str:
        lines = ["# Monitor Handler — cole no ~/.config/sway/config"]
        lines += [shlex.join(output_args(o)) for o in outputs]
        return "\n".join(lines) + "\n"

    def persist_hint(self) -> str:
        return "Para manter a configuração, adicione as linhas abaixo ao ~/.config/sway/config:"
