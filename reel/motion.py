"""Where and when the picture changes, and the camera plan that follows from it.

The recorder logs *when* each step starts (events). This module looks at the video to find
*where* things change, then plans the camera: one framing per step, eased moves between steps,
and cuts where the focused area sits still for too long.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field

SMALL_W, SMALL_H = 192, 108   # analysis resolution
SAMPLE_FPS = 10
DIFF_THRESHOLD = 24           # gray-level change that counts as "changed"
MAX_ZOOM = 2.5                # terminal stage is 2x the output (3840 wide); 3x lost all context in review
PAD = 0.05                    # breathing room around the framed area, as a share of its size
FULL_SHARE = 0.55             # a target larger than this share of the stage is shown full
LEAD = 0.9                    # the camera starts moving this long before a step starts
MOVE = 0.9                    # and takes this long (0.7 felt rushed in review)
OPEN_HOLD = 1.5               # the film opens on the whole stage at least this long
OPEN_MOVE = 1.2               # and the first push in is slower than the rest
CLOSE_MOVE = 1.2              # so is the pull back to the whole stage at the end
IDLE_MAX = 1.2                # stillness longer than this is cut
IDLE_KEEP = 0.35              # seconds kept on each side of a cut
END_ON_FULL = 1.8             # seconds the film rests on the whole stage before it fades out
TIGHT_MIN_WIDTH = 0.75        # share of a pane's width a tight framing keeps


Rect = tuple  # (x0, y0, x1, y1) in stage pixels


@dataclass
class Beat:
    """One step of the demo, in stage seconds."""
    start: float
    end: float
    focus: list = field(default_factory=list)   # rects to frame; empty = find it from the picture
    quiet_ignore: list = field(default_factory=list)  # rects whose changes do not count as activity
    label: str = ""
    tight: bool = False      # frame what changed inside the focus rects, not the whole rects
    protect: float = 0.0     # seconds after start that must not be cut (narration is playing)


class Activity:
    """Per-sample change masks of a video at SMALL_W x SMALL_H."""

    def __init__(self, masks: list, stage_w: int, stage_h: int, fps: float = SAMPLE_FPS):
        self.masks = masks          # masks[i]: bytearray, 1 where sample i differs from i-1
        self.stage_w, self.stage_h = stage_w, stage_h
        self.fps = fps

    @classmethod
    def from_frames(cls, frames: list, stage_w: int, stage_h: int, fps: float = SAMPLE_FPS):
        masks = [bytearray(SMALL_W * SMALL_H)]
        for prev, cur in zip(frames, frames[1:]):
            masks.append(bytearray(1 if abs(a - b) > DIFF_THRESHOLD else 0 for a, b in zip(prev, cur)))
        return cls(masks, stage_w, stage_h, fps)

    @classmethod
    def from_video(cls, path: str, stage_w: int, stage_h: int):
        raw = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", path, "-vf",
             f"fps={SAMPLE_FPS},scale={SMALL_W}:{SMALL_H}:flags=area,format=gray",
             "-f", "rawvideo", "-"],
            check=True, capture_output=True).stdout
        n = SMALL_W * SMALL_H
        frames = [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]
        return cls.from_frames(frames, stage_w, stage_h)

    def _small(self, r: Rect):
        sx, sy = SMALL_W / self.stage_w, SMALL_H / self.stage_h
        return (max(0, int(r[0] * sx)), max(0, int(r[1] * sy)),
                min(SMALL_W, int(r[2] * sx + 0.999)), min(SMALL_H, int(r[3] * sy + 0.999)))

    def _range(self, t0: float, t1: float):
        return range(max(1, int(t0 * self.fps)), min(len(self.masks), int(t1 * self.fps) + 1))

    def _mask(self, i: int, ignore: list = ()) -> bytearray:
        """Sample i's mask with the ignored rects blanked out."""
        m = self.masks[i]
        if not ignore:
            return m
        m = bytearray(m)
        for r in ignore:
            x0, y0, x1, y1 = self._small(r)
            blank = bytes(max(0, x1 - x0))
            for y in range(y0, y1):
                m[y * SMALL_W + x0:y * SMALL_W + x1] = blank
        return m

    def count(self, i: int, rect: Rect | None = None, ignore: list = ()) -> int:
        """Changed pixels in sample i, inside rect (whole frame if None), outside the ignored rects."""
        m = self._mask(i, ignore)
        if rect is None:
            return m.count(1)
        x0, y0, x1, y1 = self._small(rect)
        return sum(m[y * SMALL_W + x0:y * SMALL_W + x1].count(1) for y in range(y0, y1))

    def bbox(self, t0: float, t1: float, ignore: list = (), within: Rect | None = None) -> Rect | None:
        """Stage-pixel box around everything that changed between t0 and t1 (inside `within`)."""
        acc = bytearray(SMALL_W * SMALL_H)
        any_change = False
        for i in self._range(t0, t1):
            m = self._mask(i, ignore)
            if m.count(1):
                any_change = True
                acc = bytearray(a | b for a, b in zip(acc, m))
        if not any_change:
            return None
        wx0, wy0, wx1, wy1 = self._small(within) if within else (0, 0, SMALL_W, SMALL_H)
        rows = [y for y in range(wy0, wy1) if acc.find(1, y * SMALL_W + wx0, y * SMALL_W + wx1) >= 0]
        cols = [x for x in range(wx0, wx1) if any(acc[y * SMALL_W + x] for y in rows)]
        if not rows or not cols:
            return None
        sx, sy = self.stage_w / SMALL_W, self.stage_h / SMALL_H
        return (min(cols) * sx, min(rows) * sy, (max(cols) + 1) * sx, (max(rows) + 1) * sy)

    def first_change(self, t0: float, t1: float, rect: Rect | None = None, min_pixels: int = 3):
        """Stage time of the first sample after t0 with a visible change in rect, or None."""
        for i in self._range(t0, t1):
            if self.count(i, rect) >= min_pixels:
                return i / self.fps
        return None

    def idle_runs(self, t0: float, t1: float, rect: Rect | None, ignore: list = (), min_pixels: int = 2):
        """(start, end) stretches inside t0..t1 where nothing in rect changes."""
        runs, start = [], None
        for i in self._range(t0, t1):
            still = self.count(i, rect, ignore) < min_pixels
            t = i / self.fps
            if still and start is None:
                start = t
            elif not still and start is not None:
                runs.append((start, t))
                start = None
        if start is not None:
            runs.append((start, t1))
        return runs


def union(rects: list) -> Rect:
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


EDGE = 24  # stage pixels a view may reach past its pane's edge (the border between panes)


def frame(rect: Rect, stage_w: int, stage_h: int, max_zoom: float = MAX_ZOOM, within: Rect | None = None) -> dict:
    """Camera (center, zoom) that shows rect with some room, never outside the stage. A view smaller
    than `within` (the pane it frames) stays inside it, so no sliver of the neighbouring pane, with
    words cut in half, shows at the view's edge (defect b, 2026-11-24 review)."""
    x0, y0, x1, y1 = rect
    rw, rh = (x1 - x0) * (1 + 2 * PAD), (y1 - y0) * (1 + 2 * PAD)
    if rw * rh >= FULL_SHARE * stage_w * stage_h:
        return {"x": stage_w / 2, "y": stage_h / 2, "zoom": 1.0}
    zoom = max(1.0, min(max_zoom, stage_w / max(rw, 1), stage_h / max(rh, 1)))
    half_w, half_h = stage_w / zoom / 2, stage_h / zoom / 2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if within:
        wx0, wy0, wx1, wy1 = within
        if 2 * half_w <= wx1 - wx0 + 2 * EDGE:
            cx = min(max(cx, wx0 - EDGE + half_w), wx1 + EDGE - half_w)
        if 2 * half_h <= wy1 - wy0 + 2 * EDGE:
            cy = min(max(cy, wy0 - EDGE + half_h), wy1 + EDGE - half_h)
    cx = min(max(cx, half_w), stage_w - half_w)
    cy = min(max(cy, half_h), stage_h - half_h)
    return {"x": round(cx, 1), "y": round(cy, 1), "zoom": round(zoom, 3)}


def _same(a: dict, b: dict) -> bool:
    return (abs(a["zoom"] - b["zoom"]) < 0.1 * a["zoom"]
            and abs(a["x"] - b["x"]) < 40 and abs(a["y"] - b["y"]) < 40)


def plan(beats: list, act: Activity, duration: float, max_zoom: float = MAX_ZOOM) -> tuple:
    """Returns (shots, keep) for the timeline.

    Each beat gets one framing: its focus rects if given, otherwise the box around what changed
    during the beat (outside the ignored rects). Neighbouring beats with the same framing share
    one shot, so the camera does not move for nothing (CASE-A2.3).
    """
    W, H = act.stage_w, act.stage_h
    full = {"x": W / 2, "y": H / 2, "zoom": 1.0}
    cams = []
    for b in beats:
        area = union(b.focus) if b.focus else None
        if b.focus and b.tight:
            changed = act.bbox(b.start, b.end, b.quiet_ignore, within=area)
            target = _tighten(changed, area) if changed else area
        elif b.focus:
            target = area
        else:
            target = act.bbox(b.start, b.end, b.quiet_ignore)
        cams.append(frame(target, W, H, max_zoom, within=area) if target else full)

    # Always open on the whole stage, so viewers see the layout before the camera moves in.
    shots = [{"t": 0.0, **full}]
    current = shots[0]
    end_at = duration

    def back_to_full():
        nonlocal current
        if _same(current, full):
            return
        # Always end on the whole stage; in a short film, shorten the rest and the move to fit.
        t_move = max(end_at - END_ON_FULL - CLOSE_MOVE, shots[-1]["t"] + 0.3)
        move = max(0.5, min(CLOSE_MOVE, end_at - 0.4 - t_move))
        if t_move + move > end_at:
            return
        shots.append({"t": round(t_move, 3), **{k: current[k] for k in ("x", "y", "zoom")}})
        shots.append({"t": round(t_move + move, 3), **full})
        current = full

    for b, cam in zip(beats, cams):
        if _same(cam, current):
            continue
        first = len(shots) == 1
        t_move = max(b.start - LEAD, shots[-1]["t"] + 0.01, OPEN_HOLD if first else 0.0)
        move = OPEN_MOVE if first else MOVE
        shots.append({"t": round(t_move, 3), **{k: current[k] for k in ("x", "y", "zoom")}})
        shots.append({"t": round(t_move + move, 3), **cam})
        current = cam

    # End on the whole stage again, like the references: the last thing seen is the full picture.
    back_to_full()

    keep = _keep(beats, act, duration)
    return shots, keep


def _tighten(changed: Rect, area: Rect) -> Rect:
    """What changed, widened to the left edge of its pane (terminal text starts there) and given
    some lines of context above and below, never outside the pane."""
    pad = (area[3] - area[1]) * 0.12
    # At least TIGHT_MIN_WIDTH of the pane stays in view: closer than that, review showed a lone
    # prompt line in a sea of black.
    return (area[0], max(area[1], changed[1] - pad),
            max(changed[2], area[0] + (area[2] - area[0]) * TIGHT_MIN_WIDTH), min(area[3], changed[3] + pad))


def _keep(beats: list, act: Activity, duration: float) -> list:
    """Cuts stillness longer than IDLE_MAX inside a beat, away from camera moves."""
    cuts = []
    for b in beats:
        rect = union(b.focus) if b.focus else None
        lo, hi = b.start + max(0.2, b.protect), b.end - LEAD - 0.1
        if hi - lo <= IDLE_MAX:
            continue
        for a, z in act.idle_runs(lo, hi, rect, [r for r in b.quiet_ignore if rect is None or r not in b.focus]):
            if z - a > IDLE_MAX:
                cuts.append((a + IDLE_KEEP, z - IDLE_KEEP))
    keep, t = [], 0.0
    for a, z in sorted(cuts):
        if a > t:
            keep.append([round(t, 3), round(a, 3)])
        t = max(t, z)
    end = math.floor(duration * 1000) / 1000  # never past the last frame
    if end > t:
        keep.append([round(t, 3), end])
    return keep
