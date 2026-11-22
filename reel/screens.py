"""What a phone in a recording shows over time, read from its colour.

The aq walkthrough's pages are solid colours (Agent A blue, Agent B yellow), so a small patch in
the middle of a phone's screen says whose page is up at every moment. Used by the integration
cases for "B pushes A's page off the shared simulator" (CASE-C2), "each agent keeps its own"
(CASE-C3) and "a phone changes only after its command" (CASE-C3.1).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PAGE_COLOURS = {"A": (0x15, 0x96, 0xb8), "B": (0xe0, 0xa0, 0x30)}
TOLERANCE = 60  # summed RGB distance; video compression shifts a solid colour by far less


def classify(rgb: tuple) -> str | None:
    best = min(PAGE_COLOURS, key=lambda k: sum(abs(a - b) for a, b in zip(rgb, PAGE_COLOURS[k])))
    return best if sum(abs(a - b) for a, b in zip(rgb, PAGE_COLOURS[best])) <= TOLERANCE else None


def timeline(video: Path, rect, fps: float = 10) -> list:
    """[(seconds, "A" | "B" | None)] for the screen inside rect = [x0, y0, x1, y1] (stage pixels)."""
    x0, y0, x1, y1 = (int(v) for v in rect)
    w, h = (x1 - x0) // 4, (y1 - y0) // 8
    cx, cy = x0 + (x1 - x0 - w) // 2, y0 + (y1 - y0) // 4  # above the page's centred text
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf",
                          f"fps={fps},crop={w}:{h}:{cx}:{cy},scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return [(round(i / fps, 2), classify(tuple(raw[i * 3:i * 3 + 3]))) for i in range(len(raw) // 3)]


def first(tl: list, label: str, after: float = 0.0) -> float | None:
    return next((t for t, v in tl if v == label and t >= after), None)
