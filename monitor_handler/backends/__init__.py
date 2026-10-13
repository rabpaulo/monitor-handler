"""Backend auto-detection.

Desktop-specific backends come first because GNOME and KDE override whatever
xrandr does, even on their X11 sessions."""

from __future__ import annotations

from .base import Backend, BackendError
from .gnome import GnomeBackend
from .hyprland import HyprlandBackend
from .kscreen import KScreenBackend
from .sway import SwayBackend
from .wlr_randr import WlrRandrBackend
from .xrandr import XrandrBackend

BACKENDS: list[type[Backend]] = [
    GnomeBackend,
    KScreenBackend,
    HyprlandBackend,
    SwayBackend,
    WlrRandrBackend,
    XrandrBackend,
]


def detect(prefer: str | None = None) -> Backend:
    if prefer:
        for cls in BACKENDS:
            if cls.id == prefer:
                return cls()
        raise BackendError(f"Backend desconhecido: {prefer}. Opções: {', '.join(c.id for c in BACKENDS)}")
    for cls in BACKENDS:
        if cls.available():
            return cls()
    raise BackendError(
        "Nenhum backend suportado foi encontrado.\n"
        "X11: instale xrandr. Wayland: GNOME, KDE (kscreen-doctor), Hyprland, Sway "
        "ou outro compositor wlroots com wlr-randr.")


__all__ = ["BACKENDS", "Backend", "BackendError", "detect"]
