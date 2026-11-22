"""The timeline: everything the composers need, in one JSON file.

A timeline says which parts of the stage video to keep, where the camera looks and when,
and which captions and cards to show; compose_ffmpeg.py renders it.

All times in `shots`, `captions` and `keep` are seconds of the stage video (before cuts).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MAX_ZOOM = 3.0


class TimelineError(ValueError):
    """The timeline cannot be rendered; the message names the field."""


@dataclass
class Shot:
    t: float      # the camera arrives here at time t (stage seconds)
    x: float      # center, stage pixels
    y: float
    zoom: float   # 1.0 shows the whole stage


def load(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    validate(data)
    return data


def save(data: dict, path: Path) -> None:
    validate(data)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _need(obj: dict, key: str, where: str):
    if key not in obj:
        raise TimelineError(f"{where}: missing '{key}'")
    return obj[key]


def validate(data: dict) -> None:
    """Raises TimelineError for anything that would render wrong (CASE-A1.1)."""
    stage = _need(data, "stage", "timeline")
    w, h, dur = (_need(stage, k, "stage") for k in ("width", "height", "duration"))
    if w <= 0 or h <= 0 or dur <= 0:
        raise TimelineError("stage: width, height and duration must be positive")
    out = _need(data, "output", "timeline")
    for k in ("width", "height", "fps"):
        if _need(out, k, "output") <= 0:
            raise TimelineError(f"output: {k} must be positive")

    keep = _need(data, "keep", "timeline")
    if not keep:
        raise TimelineError("keep: no part of the stage video is kept")
    prev_end = -1.0
    for i, seg in enumerate(keep):
        a, b = seg
        if not (0 <= a < b <= dur + 1e-3):
            raise TimelineError(f"keep[{i}]: [{a}, {b}] is not inside 0..{dur} or is empty")
        if a < prev_end:
            raise TimelineError(f"keep[{i}]: starts at {a}, before the previous part ends at {prev_end}")
        prev_end = b

    shots = _need(data, "shots", "timeline")
    if not shots:
        raise TimelineError("shots: the camera has no shot")
    prev_t = -1.0
    for i, s in enumerate(shots):
        t, x, y, z = (_need(s, k, f"shots[{i}]") for k in ("t", "x", "y", "zoom"))
        if t < prev_t:
            raise TimelineError(f"shots[{i}]: time {t} is before the previous shot at {prev_t}")
        prev_t = t
        if not (1.0 <= z <= MAX_ZOOM):
            raise TimelineError(f"shots[{i}]: zoom {z} is outside 1..{MAX_ZOOM}")
        half_w, half_h = w / z / 2, h / z / 2
        if x - half_w < -0.5 or x + half_w > w + 0.5 or y - half_h < -0.5 or y + half_h > h + 0.5:
            raise TimelineError(f"shots[{i}]: the view at ({x}, {y}) zoom {z} goes outside the {w}x{h} stage")

    for i, c in enumerate(data.get("captions", [])):
        a, b, text = (_need(c, k, f"captions[{i}]") for k in ("start", "end", "text"))
        if not (0 <= a < b <= dur + 1e-3):
            raise TimelineError(f"captions[{i}]: [{a}, {b}] is not inside 0..{dur} or is empty")
        if not text.strip():
            raise TimelineError(f"captions[{i}]: empty text")

    for key in ("intro", "outro"):
        card = data.get(key)
        if card is not None:
            if _need(card, "seconds", key) <= 0:
                raise TimelineError(f"{key}: seconds must be positive")
            _need(card, "title", key)


def output_time(keep: list, t: float) -> float | None:
    """Maps a stage time to the time after cuts (without intro); None if t was cut."""
    acc = 0.0
    for a, b in keep:
        if t < a:
            return None
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return None


def kept_seconds(keep: list) -> float:
    return sum(b - a for a, b in keep)


def total_seconds(data: dict) -> float:
    extra = sum(data[k]["seconds"] for k in ("intro", "outro") if data.get(k))
    return kept_seconds(data["keep"]) + extra
