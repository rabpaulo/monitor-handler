"""X11 backend built on the xrandr command line tool."""

from __future__ import annotations

import os
import re

from ..model import (
    FEAT_BIT_DEPTH, FEAT_BRIGHTNESS, FEAT_MIRROR, FEAT_PRIMARY, FEAT_RGB_RANGE,
    Mode, Output,
)
from .base import Backend, have, run

ROT_TO_X = {0: "normal", 90: "right", 180: "inverted", 270: "left"}
X_TO_ROT = {v: k for k, v in ROT_TO_X.items()}

HEADER_RE = re.compile(
    r"^(?P<name>\S+) (?P<state>connected|disconnected)(?P<primary> primary)?"
    r"(?: (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?"
    r"(?: \(0x[0-9a-f]+\))?"
    r"(?: (?P<rot>normal|left|inverted|right))?"
)
MODE_RE = re.compile(r"^\s+(?P<w>\d+)x(?P<h>\d+)(?P<i>i?)\s+(?P<rates>.*)$")
RATE_RE = re.compile(r"(\d+\.\d+)(\*?)\s?(\+?)")
PROP_RE = re.compile(r"^\t(?P<key>[^\t:][^:]*):\s?(?P<val>.*?)\s*$")
SUB_RE = re.compile(r"^\t\t(?P<kind>supported|range):\s*(?P<val>.*?)\s*$")


def edid_name(hex_blob: str) -> str:
    try:
        data = bytes.fromhex(hex_blob)
    except ValueError:
        return ""
    if len(data) < 128:
        return ""
    make = ""
    raw = (data[8] << 8) | data[9]
    letters = [(raw >> 10) & 0x1F, (raw >> 5) & 0x1F, raw & 0x1F]
    if all(1 <= c <= 26 for c in letters):
        make = "".join(chr(ord("A") + c - 1) for c in letters)
    model = ""
    for off in (54, 72, 90, 108):
        d = data[off:off + 18]
        if d[:3] == b"\0\0\0" and d[3] == 0xFC:
            model = d[5:18].decode("cp437", "replace").split("\n")[0].strip()
    return " ".join(p for p in (make, model) if p)


def parse_prop(text: str, verbose_text: str = "") -> list[Output]:
    outputs: list[Output] = []
    cur: Output | None = None
    cur_key: str | None = None
    edid_hex = ""
    props: dict[str, dict] = {}

    def finish():
        if cur is None:
            return
        if edid_hex:
            cur.description = edid_name(edid_hex)
        _apply_props(cur, props)

    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m and not line.startswith((" ", "\t")):
            finish()
            cur, cur_key, edid_hex, props = None, None, "", {}
            if m["state"] != "connected":
                continue
            cur = Output(name=m["name"], primary=bool(m["primary"]))
            cur.enabled = m["w"] is not None
            if cur.enabled:
                cur.x, cur.y = int(m["x"]), int(m["y"])
                cur.rotation = X_TO_ROT.get(m["rot"] or "normal", 0)
            outputs.append(cur)
            continue
        if cur is None:
            continue
        mm = MODE_RE.match(line)
        if mm and not line.startswith("\t"):
            if mm["i"]:
                continue
            w, h = int(mm["w"]), int(mm["h"])
            for rate, star, plus in RATE_RE.findall(mm["rates"]):
                mode = Mode(w, h, float(rate), preferred=bool(plus), id=f"{w}x{h}")
                cur.modes.append(mode)
                if star:
                    cur.width, cur.height, cur.refresh = w, h, float(rate)
            continue
        pm = PROP_RE.match(line)
        if pm:
            cur_key = pm["key"].strip()
            props[cur_key] = {"value": pm["val"]}
            continue
        sm = SUB_RE.match(line)
        if sm and cur_key:
            props[cur_key][sm["kind"]] = sm["val"]
            continue
        if cur_key == "EDID" and line.startswith("\t\t"):
            edid_hex += line.strip()
    finish()

    brightness = parse_brightness(verbose_text)
    for o in outputs:
        if o.name in brightness:
            o.brightness = brightness[o.name]
        if not o.enabled:
            pref = o.preferred_mode()
            if pref:
                o.width, o.height, o.refresh = pref.width, pref.height, pref.refresh
    return outputs


def _apply_props(out: Output, props: dict[str, dict]) -> None:
    bpc = props.get("max bpc")
    if bpc:
        try:
            out.bit_depth = int(bpc["value"])
        except ValueError:
            pass
        rng = re.findall(r"\d+", bpc.get("range", ""))
        if len(rng) == 2:
            lo, hi = int(rng[0]), int(rng[1])
            out.bit_depth_options = [b for b in (6, 8, 10, 12, 16) if lo <= b <= hi]
    rgb = props.get("Broadcast RGB")
    if rgb:
        out.rgb_range = rgb["value"]
        out.rgb_range_options = [s.strip() for s in rgb.get("supported", "").split(",") if s.strip()]
    vrr = props.get("vrr_capable")
    if vrr:
        out.extra["vrr_capable"] = vrr["value"] == "1"


def parse_brightness(verbose_text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    name = None
    for line in verbose_text.splitlines():
        if line and not line[0].isspace():
            name = line.split(" ", 1)[0]
        elif name and line.strip().startswith("Brightness:"):
            try:
                result[name] = float(line.split(":", 1)[1])
            except ValueError:
                pass
    return result


def build_command(outputs: list[Output], driver_props: bool = True) -> list[str]:
    """xrandr invocation for `outputs`.

    With driver_props=False (outputs read by another backend) the X11-only
    properties are left out and brightness is only set when it differs from 100%."""
    cmd = ["xrandr"]
    for o in outputs:
        cmd += ["--output", o.name]
        if not o.enabled:
            cmd.append("--off")
            continue
        cmd += ["--mode", f"{o.width}x{o.height}"]
        if o.refresh:
            cmd += ["--rate", f"{o.refresh:.2f}"]
        if o.mirror_of:
            cmd += ["--same-as", o.mirror_of]
        else:
            cmd += ["--pos", f"{o.x}x{o.y}"]
        cmd += ["--rotate", ROT_TO_X.get(o.rotation, "normal")]
        if o.primary:
            cmd.append("--primary")
        if driver_props or abs(o.brightness - 1.0) > 0.005:
            cmd += ["--brightness", f"{o.brightness:.2f}"]
        if not driver_props:
            continue
        if o.bit_depth is not None and o.bit_depth_options:
            cmd += ["--set", "max bpc", str(o.bit_depth)]
        if o.rgb_range and o.rgb_range_options:
            cmd += ["--set", "Broadcast RGB", o.rgb_range]
    return cmd


class XrandrBackend(Backend):
    id = "xrandr"
    name = "X11 (xrandr)"
    features = frozenset({FEAT_PRIMARY, FEAT_MIRROR, FEAT_BIT_DEPTH, FEAT_BRIGHTNESS, FEAT_RGB_RANGE})

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY") and have("xrandr")

    def list_outputs(self) -> list[Output]:
        return parse_prop(run(["xrandr", "--prop"]), run(["xrandr", "--verbose"], check=False))

    def commands(self, outputs: list[Output]) -> list[list[str]]:
        return [build_command(outputs)]

    def persist_hint(self) -> str:
        return ("No X11 a configuração não é salva sozinha. Adicione a linha abaixo ao "
                "~/.xinitrc (antes do exec do seu WM), ao autostart do seu WM ou ao ~/.xprofile:")
