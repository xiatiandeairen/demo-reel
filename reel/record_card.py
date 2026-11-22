"""A card scene: a few large lines of text, with figures computed from what other scenes logged.

Spec fields for kind = "card":

    [card]
    seconds = 4
    lines = ["Builds run: {without} → {with}"]
    [card.values]                 # each value is the output of a shell command (run in the spec's folder)
    without = "wc -l < /tmp/aq-demo-without/runs.log | tr -d ' '"

A command that fails or prints nothing stops the film, so a card never shows a made-up or empty
figure (CASE-C5.1). Optional [[step]] entries (at, say) narrate the card.
"""
from __future__ import annotations

import json
import string
import subprocess
from pathlib import Path

from . import cards

W, H, FPS = 1920, 1080, 30


class CardError(RuntimeError):
    pass


def values(commands: dict, cwd: str) -> dict:
    out = {}
    for name, cmd in commands.items():
        r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            raise CardError(f"card value {name}: `{cmd}` failed: {(r.stderr or r.stdout).strip()}")
        v = r.stdout.strip()
        if not v:
            raise CardError(f"card value {name}: `{cmd}` printed nothing (empty)")
        out[name] = v
    return out


def fill(lines: list, vals: dict) -> list:
    filled = []
    for line in lines:
        for _, field, _, _ in string.Formatter().parse(line):
            if field and field not in vals:
                raise CardError(f"card line {line!r} uses {{{field}}}, which [card.values] does not define")
        filled.append(line.format(**vals))
    return filled


def beats_for(steps: list, seconds: float) -> list:
    """Narration beats for a step-less scene: each step's `at` until the next one (or the end)."""
    beats = []
    ats = [float(s.get("at", 0.0)) for s in steps]
    for i, (s, at) in enumerate(zip(steps, ats)):
        end = ats[i + 1] if i + 1 < len(ats) else seconds
        beats.append({"start": at, "end": round(end, 3), "label": f"step {i + 1}", "focus": [], "ignore": [],
                      "full": True, "narration": s.get("_narration", 0.0)})
    return beats


def write_events(out: Path, kind: str, seconds: float, steps: list) -> Path:
    events = {"kind": kind, "stage": {"path": "stage.mp4", "width": W, "height": H, "duration": seconds, "fps": FPS},
              "regions": {"full": [0, 0, W, H]}, "beats": beats_for(steps, seconds)}
    for s, b in zip(steps, events["beats"]):
        if b["start"] + s.get("_narration", 0.0) > seconds + 0.05:
            raise CardError(f"{kind}: the sentence at {b['start']} s runs past the scene's {seconds} s")
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path


def record(spec: dict, out: Path) -> Path:
    card = spec.get("card", {})
    if not card.get("lines"):
        raise CardError("[card] needs lines")
    seconds = float(card.get("seconds", 4))
    lines = fill(card["lines"], values(card.get("values", {}), spec["_dir"]))
    out = Path(out)
    png = out / "card.png"
    cards.stat_card(png, lines, spec["accent"], W, H)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}",
                    "-i", str(png), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out / "stage.mp4")],
                   check=True)
    (out / "card.json").write_text(json.dumps({"lines": lines}, indent=2, ensure_ascii=False) + "\n")
    return write_events(out, "card", seconds, spec.get("step", []))
