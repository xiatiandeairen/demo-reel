"""A card: a few large lines of text, or bar charts, with figures computed from what the scenes logged.

Cards are written in reel.toml (docs/design.md):

    [card.result]
    lines = ["Builds run: {without} → {with}"]
    [card.result.values]          # each value is a shell command's output (run in the reel's folder);
    without = "wc -l < {files:without}/runs.log | tr -d ' '"   # {files:<scene id>}: what that scene kept

A card can show bar charts instead of (or below) lines: each group compares a few values, bars as
long as their values with the largest filling the track, growing in one after another.

    [[card.result.bars]]
    title = "First build in a new worktree"
    unit = "s"
    items = [{ label = "xcodebuild", value = { scene = "without", timer = "xcodebuild" } },
             { label = "agb", value = "<command>" }]     # a command's output, or a scene's timer bar

A command that fails or prints nothing (or, for a bar, not a number) stops the reel, so a card never
shows a made-up or empty figure (CASE-C5.1, CASE-D1.3). How long a card stays follows from its content.
"""
from __future__ import annotations

import json
import re
import shlex
import string
import subprocess
from pathlib import Path

from . import cards

W, H, FPS = 1920, 1080, 30


class CardError(RuntimeError):
    pass


FILES_REF = re.compile(r"\{files:([^}]+)\}")


def _kept_files(cmd: str, scenes: Path) -> str:
    """{files:<scene id>} in a command becomes that scene's kept-files folder, take/files (CASE-D3.1)."""
    def sub(m):
        kept = Path(scenes) / m.group(1) / "take" / "files"
        if not kept.exists():
            raise CardError(f"card: scene {m.group(1)} has kept no files (keep_files), or has not been recorded")
        return shlex.quote(str(kept))
    return FILES_REF.sub(sub, cmd)


def values(commands: dict, cwd: str, scenes: Path) -> dict:
    """Each command's output. scenes: the reel's scenes state folder (paths.state_dir(reel) / "scenes")."""
    out = {}
    for name, cmd in commands.items():
        cmd = _kept_files(cmd, scenes)
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


BAR_GROW, BAR_STAGGER = 0.9, 0.35  # seconds each bar takes to grow, and between bars starting


def _number(text: str) -> float:
    return float(text.replace(",", "").strip())


def scene_timer(scenes: Path, sid: str, label: str) -> float:
    """Seconds of the timer bar `label` in a scene's latest edit, so a card and that bar agree."""
    tl = Path(scenes) / sid / "edit" / "timeline.json"
    if not tl.exists():
        raise CardError(f"bar from scene {sid}: that scene has not been recorded")
    for tm in json.loads(tl.read_text()).get("timers", []):
        if tm["label"] == label:
            return float(tm["seconds"])
    raise CardError(f"bar from scene {sid}: it has no timer labelled {label!r}")


def bar_groups(groups: list, cwd: str, scenes: Path) -> list:
    """Groups with each item's value, display text and share of its group's largest value (CASE-D1.3)."""
    out = []
    for g in groups:
        items = []
        for it in g["items"]:
            if isinstance(it["value"], dict):  # { scene = "<id>", timer = "<label>" }: the same figure as that timer bar
                raw = f"{scene_timer(scenes, it['value']['scene'], it['value']['timer']):.1f}"
            else:
                raw = values({it["label"]: it["value"]}, cwd, scenes)[it["label"]]
            try:
                v = _number(raw)
            except ValueError:
                raise CardError(f"bar {it['label']}: `{it['value']}` printed {raw!r}, not a number")
            unit = g.get("unit", "")
            items.append({"label": it["label"], "value": v, "text": f"{raw}{' ' + unit if unit else ''}"})
        top = max((i["value"] for i in items), default=0) or 1
        for i in items:
            i["share"] = i["value"] / top
        out.append({"title": g.get("title", ""), "items": items})
    return out


LEAD_IN, GAP = 0.4, 0.3  # seconds before the first sentence, and between sentences


def beats_for(steps: list, seconds: float) -> list:
    """Narration beats for a scene without actions (an animation): the first sentence after LEAD_IN, each
    next one GAP after the previous has been spoken (or read), the last until the end."""
    ats, t = [], LEAD_IN
    for s in steps:
        ats.append(round(t, 3))
        t += (s.get("_narration") or READ_BASE) + GAP
    beats = []
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


READ_LINE, READ_BASE, READ_MIN = 1.2, 1.5, 2.5  # seconds to read a card: per line, plus a base


def card_seconds(lines: list, groups: list) -> float:
    """How long a card stays: long enough to read its lines, and for its bars to grow and be read."""
    read = max(READ_MIN, READ_BASE + READ_LINE * len(lines))
    bars = sum(len(g["items"]) for g in groups)
    grown = 0.4 + max(0, bars - 1) * BAR_STAGGER + BAR_GROW + READ_LINE * len(groups) + READ_BASE if bars else 0
    return round(max(read, grown), 1)


def resolve(spec: dict) -> tuple:
    """(lines, bar groups) with every figure computed now; spec["_scenes"] is the reel's scenes state."""
    card = spec["card"]
    lines = fill(card.get("lines", []), values(card.get("values", {}), spec["_dir"], spec["_scenes"]))
    return lines, bar_groups(card.get("bars", []), spec["_dir"], spec["_scenes"])


def record(spec: dict, out: Path, resolved: tuple | None = None) -> Path:
    lines, groups = resolved or resolve(spec)
    seconds = card_seconds(lines, groups)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / "card.png"
    if not groups:
        cards.stat_card(png, lines, spec["accent"], W, H)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}",
                        "-i", str(png), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out / "stage.mp4")],
                       check=True)
    else:
        bars = cards.bar_card(png, lines, groups, spec["accent"], W, H)  # [(x, y, full width, height, colour)]
        inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}", "-i", str(png)]
        g, last = [], "0:v"
        for k, (x, y, full, h, colour) in enumerate(bars):
            start = 0.4 + k * BAR_STAGGER
            inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s={max(2, full)}x{h}:d={seconds:.3f}:r={FPS}"]
            g.append(f"[{k + 1}:v]scale=w='max(2,{full}*min(1,max(0,t-{start:.2f})/{BAR_GROW}))':h={h}:eval=frame[b{k}]")
            g.append(f"[{last}][b{k}]overlay={x}:{y}:eval=frame:enable='gte(t,{start:.2f})'[o{k}]")
            last = f"o{k}"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(g), "-map", f"[{last}]",
                        "-t", f"{seconds:.3f}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                        str(out / "stage.mp4")], check=True)
    (out / "card.json").write_text(json.dumps({"lines": lines, "bars": groups}, indent=2, ensure_ascii=False) + "\n")
    return write_events(out, "card", seconds, spec.get("step", []))
