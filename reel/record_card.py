"""A card scene: a few large lines of text, with figures computed from what other scenes logged.

Spec fields for kind = "card":

    [card]
    seconds = 4
    lines = ["Builds run: {without} → {with}"]
    [card.values]                 # each value is the output of a shell command (run in the spec's folder);
                                  # {files:<scene>.toml} is the files that scene kept (its keep_files)
    without = "wc -l < {files:without-aq.toml}/app/runs.log | tr -d ' '"

A card can show bar charts instead of (or below) lines: each group compares a few values, bars as
long as their values with the largest filling the track, growing in one after another.

    [[card.bars]]
    title = "First build in a new worktree"
    unit = "s"
    items = [{ label = "xcodebuild", value = { scene = "without-agb.toml", timer = "xcodebuild" } },
             { label = "agb", value = "<command>" }]     # a command's output, or another scene's timer bar

A command that fails or prints nothing (or, for a bar, not a number) stops the film, so a card never
shows a made-up or empty figure (CASE-C5.1, CASE-D1.3). Optional [[step]] entries (at, say) narrate it.
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


def _kept_files(cmd: str, cwd: str) -> str:
    """{files:<scene>.toml} in a command becomes that scene's kept-files directory (CASE-D3.1)."""
    from . import paths, spec as spec_mod

    def sub(m):
        scene = (Path(cwd) / m.group(1)).resolve()
        if not scene.exists():
            raise CardError(f"card: {m.group(1)} not found")
        return shlex.quote(str(paths.state_dir(spec_mod.load(scene)) / "files"))
    return FILES_REF.sub(sub, cmd)


def values(commands: dict, cwd: str) -> dict:
    out = {}
    for name, cmd in commands.items():
        cmd = _kept_files(cmd, cwd)
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


def scene_timer(scene_spec: Path, label: str) -> float:
    """Seconds of the timer bar `label` in another scene's last recording, so a card and that bar agree."""
    from . import paths, spec as spec_mod
    sc = spec_mod.load(scene_spec)
    tl = paths.state_dir(sc) / "timeline.json"
    if not tl.exists():
        raise CardError(f"bar from {scene_spec.name}: that scene has not been recorded")
    for tm in json.loads(tl.read_text()).get("timers", []):
        if tm["label"] == label:
            return float(tm["seconds"])
    raise CardError(f"bar from {scene_spec.name}: it has no timer labelled {label!r}")


def bar_groups(groups: list, cwd: str) -> list:
    """Groups with each item's value, display text and share of its group's largest value (CASE-D1.3)."""
    out = []
    for g in groups:
        items = []
        for it in g["items"]:
            if isinstance(it["value"], dict):  # { scene = "<spec>.toml", timer = "<label>" }: the same figure as that timer bar
                raw = f"{scene_timer(Path(cwd) / it['value']['scene'], it['value']['timer']):.1f}"
            else:
                raw = values({it["label"]: it["value"]}, cwd)[it["label"]]
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
    if not card.get("lines") and not card.get("bars"):
        raise CardError("[card] needs lines or bars")
    seconds = float(card.get("seconds", 4))
    lines = fill(card.get("lines", []), values(card.get("values", {}), spec["_dir"]))
    groups = bar_groups(card.get("bars", []), spec["_dir"])
    out = Path(out)
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
