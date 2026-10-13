"""Geometry helpers for arranging outputs relative to each other."""

from __future__ import annotations

from .model import Output

SIDES = ("right", "left", "above", "below", "mirror")
ALIGNS = ("start", "center", "end")


def active(outputs: list[Output]) -> list[Output]:
    return [o for o in outputs if o.enabled]


def place_relative(out: Output, ref: Output, side: str, align: str = "start") -> None:
    """Move `out` so it sits on `side` of `ref`, aligned along the shared edge."""
    if side == "mirror":
        out.mirror_of = ref.name
        out.x, out.y = ref.x, ref.y
        return
    out.mirror_of = None
    rx, ry, rw, rh = ref.rect()
    w, h = out.logical_size()

    def along(ref_start: int, ref_len: int, own_len: int) -> int:
        if align == "center":
            return ref_start + (ref_len - own_len) // 2
        if align == "end":
            return ref_start + ref_len - own_len
        return ref_start

    if side == "right":
        out.x, out.y = rx + rw, along(ry, rh, h)
    elif side == "left":
        out.x, out.y = rx - w, along(ry, rh, h)
    elif side == "above":
        out.x, out.y = along(rx, rw, w), ry - h
    elif side == "below":
        out.x, out.y = along(rx, rw, w), ry + rh
    else:
        raise ValueError(f"unknown side {side!r}")


def relation(out: Output, ref: Output) -> tuple[str, str] | None:
    """Best-effort inverse of place_relative: (side, align) or None if detached."""
    if out.mirror_of == ref.name:
        return ("mirror", "start")
    x, y, w, h = out.rect()
    rx, ry, rw, rh = ref.rect()

    def align_of(start: int, length: int, rstart: int, rlen: int) -> str:
        if start == rstart:
            return "start"
        if start + length == rstart + rlen:
            return "end"
        if start == rstart + (rlen - length) // 2:
            return "center"
        return "start"

    if x == rx + rw:
        return ("right", align_of(y, h, ry, rh))
    if x + w == rx:
        return ("left", align_of(y, h, ry, rh))
    if y + h == ry:
        return ("above", align_of(x, w, rx, rw))
    if y == ry + rh:
        return ("below", align_of(x, w, rx, rw))
    return None


def sync_mirrors(outputs: list[Output]) -> None:
    by_name = {o.name: o for o in outputs}
    for o in outputs:
        target = by_name.get(o.mirror_of or "")
        if o.mirror_of and (target is None or not target.enabled or target is o):
            o.mirror_of = None
        elif target is not None:
            o.x, o.y = target.x, target.y


def normalize(outputs: list[Output]) -> None:
    """Shift the layout so the top-left-most active output starts at (0, 0)."""
    sync_mirrors(outputs)
    act = active(outputs)
    if not act:
        return
    min_x = min(o.x for o in act)
    min_y = min(o.y for o in act)
    if min_x or min_y:
        for o in outputs:
            o.x -= min_x
            o.y -= min_y


def overlaps(a: Output, b: Output) -> bool:
    ax, ay, aw, ah = a.rect()
    bx, by, bw, bh = b.rect()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def snap(out: Output, others: list[Output], threshold: int) -> None:
    """Pull `out` onto nearby edges of the other outputs (used while dragging)."""
    x, y, w, h = out.rect()
    best_dx, best_dy = threshold + 1, threshold + 1
    for o in others:
        if o is out or not o.enabled or o.mirror_of:
            continue
        ox, oy, ow, oh = o.rect()
        for cand in (ox - w, ox + ow, ox, ox + ow - w):
            if abs(cand - x) < abs(best_dx):
                best_dx = cand - x
        for cand in (oy - h, oy + oh, oy, oy + oh - h):
            if abs(cand - y) < abs(best_dy):
                best_dy = cand - y
    if abs(best_dx) <= threshold:
        out.x += best_dx
    if abs(best_dy) <= threshold:
        out.y += best_dy


def validate(outputs: list[Output]) -> list[str]:
    """Human-readable problems that would make the layout fail or look wrong."""
    problems = []
    act = [o for o in active(outputs) if not o.mirror_of]
    if not active(outputs):
        problems.append("Pelo menos um monitor precisa ficar ligado.")
    for i, a in enumerate(act):
        for b in act[i + 1:]:
            if overlaps(a, b):
                problems.append(f"{a.name} e {b.name} estão sobrepostos.")
    return problems
