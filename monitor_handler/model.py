"""Backend-independent description of displays and their settings."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

# Rotation is always stored in degrees, clockwise (same meaning as xrandr's
# "right" = 90). Each backend translates to its own vocabulary.
ROTATIONS = (0, 90, 180, 270)

# Optional features. A backend advertises the subset it can actually change,
# and the GUI only shows controls for those.
FEAT_PRIMARY = "primary"
FEAT_SCALE = "scale"
FEAT_VRR = "vrr"
FEAT_HDR = "hdr"
FEAT_BIT_DEPTH = "bit_depth"
FEAT_MIRROR = "mirror"
FEAT_BRIGHTNESS = "brightness"
FEAT_RGB_RANGE = "rgb_range"


@dataclass
class Mode:
    width: int
    height: int
    refresh: float  # Hz
    preferred: bool = False
    # Backend-specific identifier (xrandr mode name, KDE mode id, GNOME mode id...)
    id: str = ""

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

    def label(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class Output:
    name: str
    description: str = ""
    enabled: bool = True
    modes: list[Mode] = field(default_factory=list)
    width: int = 0
    height: int = 0
    refresh: float = 0.0
    x: int = 0
    y: int = 0
    rotation: int = 0
    scale: float = 1.0
    scale_options: list[float] = field(default_factory=list)
    # False when the compositor lays outputs out in physical pixels (GNOME "physical" mode)
    layout_scaled: bool = True
    primary: bool = False
    mirror_of: str | None = None

    vrr_supported: bool = False
    vrr: bool = False
    hdr_supported: bool = False
    hdr: bool = False
    bit_depth: int | None = None
    bit_depth_options: list[int] = field(default_factory=list)
    brightness: float = 1.0
    rgb_range: str | None = None
    rgb_range_options: list[str] = field(default_factory=list)

    # Opaque data a backend needs to round-trip (connector ids, serials...).
    extra: dict = field(default_factory=dict)

    # ---- helpers -------------------------------------------------------
    def resolutions(self) -> list[tuple[int, int]]:
        seen: list[tuple[int, int]] = []
        for m in sorted(self.modes, key=lambda m: (m.width * m.height, m.width), reverse=True):
            if m.resolution not in seen:
                seen.append(m.resolution)
        return seen

    def rates_for(self, width: int, height: int) -> list[float]:
        rates = sorted({round(m.refresh, 2) for m in self.modes if m.resolution == (width, height)}, reverse=True)
        return rates

    def find_mode(self, width: int | None = None, height: int | None = None, refresh: float | None = None) -> Mode | None:
        width = self.width if width is None else width
        height = self.height if height is None else height
        refresh = self.refresh if refresh is None else refresh
        candidates = [m for m in self.modes if m.resolution == (width, height)]
        if not candidates:
            return None
        return min(candidates, key=lambda m: abs(m.refresh - refresh))

    def preferred_mode(self) -> Mode | None:
        for m in self.modes:
            if m.preferred:
                return m
        return self.modes[0] if self.modes else None

    def logical_size(self) -> tuple[int, int]:
        """Size this output occupies in the global layout (rotation + scale applied)."""
        w, h = self.width, self.height
        if self.rotation in (90, 270):
            w, h = h, w
        s = (self.scale or 1.0) if self.layout_scaled else 1.0
        return (round(w / s), round(h / s))

    def rect(self) -> tuple[int, int, int, int]:
        w, h = self.logical_size()
        return (self.x, self.y, w, h)

    def clone(self) -> "Output":
        return copy.deepcopy(self)


def clone_all(outputs: list[Output]) -> list[Output]:
    return [o.clone() for o in outputs]
