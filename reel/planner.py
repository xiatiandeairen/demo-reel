"""Turns a recording (stage video + events.json) into a timeline.json for the composers."""
from __future__ import annotations

import json
from pathlib import Path

from . import motion, timeline

INTRO_SECONDS = 1.8
OUTRO_SECONDS = 1.8


ANCHOR_SEARCH = 3.0   # seconds around a logged command start to look for its Enter on screen
ANCHOR_STILL = 0.15   # the tape pauses 0.2 s between typing and Enter


def _enter_seen(act, region, t: float):
    """Video time of the first change after a short stillness near t (the Enter after typing)."""
    best = None
    lo, hi = max(0.0, t - ANCHOR_SEARCH), t + ANCHOR_SEARCH
    still_since = None
    for i in act._range(lo, hi):
        ti = i / act.fps
        if act.count(i, region) < 3:
            still_since = ti if still_since is None else still_since
            continue
        if still_since is not None and ti - still_since >= ANCHOR_STILL - 1e-6:
            if best is None or abs(ti - t) < abs(best - t):
                best = ti
        still_since = None
    return best


def refine(ev: dict, act) -> dict:
    """Corrects the linear wall-clock mapping where VHS dropped frames (CASE-A2.1).

    Anchors are typed commands: logged start vs the Enter seen in their pane. Times between
    anchors are shifted by the interpolated offset; before the first and after the last anchor
    by that anchor's offset.
    """
    anchors = []
    for c in ev.get("commands", []):
        region = ev.get("regions", {}).get(c["pane"])
        if region and c.get("end") is not None or region and "exit" not in c and c["start"] > 0.5:
            seen = _enter_seen(act, tuple(region), c["start"])
            if seen is not None:
                anchors.append((c["start"], seen - c["start"]))
    anchors.sort()
    if not anchors:
        return ev

    def fix(t):
        if t <= anchors[0][0]:
            return round(max(0.0, t + anchors[0][1]), 3)
        for (t0, d0), (t1, d1) in zip(anchors, anchors[1:]):
            if t <= t1:
                return round(t + d0 + (d1 - d0) * (t - t0) / max(t1 - t0, 1e-6), 3)
        return round(min(ev["stage"]["duration"], t + anchors[-1][1]), 3)

    for b in ev["beats"]:
        b["start"], b["end"] = fix(b["start"]), fix(b["end"])
    for c in ev.get("commands", []):
        c["start_refined"] = fix(c["start"])
    ev["anchors"] = [{"logged": a, "offset": round(d, 3)} for a, d in anchors]
    return ev


SQUEEZE_KEEP = 0.5  # seconds kept after a squeezed command starts
SQUEEZE_TAIL = 1.5  # ... and before it ends: a command that waits for the screen notices a change up to
                    # about a second late, so the change itself must stay in (2026-11-22 dogfood)
SQUEEZE_MIN = 1.5   # a shorter middle is left alone


def _step_command(step: dict, beat: dict, commands: list) -> dict | None:
    """The finished command a typed step started: in its pane, entered during the step, and starting with
    the same word as what the step typed (the previous step's short command can fall inside the window)."""
    pane = step.get("pane")
    mine = [c for c in commands if c.get("end") is not None and (pane is None or c["pane"] == pane)
            and beat["start"] - 0.5 <= c["start"] <= beat["end"] + 0.5]
    word = (step.get("type") or "").split()[:1]
    same = [c for c in mine if word and c.get("cmd", "").replace("\\ ", " ").split()[:1] == word]
    return (same or mine or [None])[0]


def keep_spans(steps: list, beats: list, commands: list) -> list:
    """Stage spans that must play uncut (CASE-D1.1): the whole run of commands in steps with a `timer`,
    so a comparison of durations is shown in real time."""
    spans = []
    for s, b in zip(steps, beats):
        if s.get("type") and s.get("timer"):
            c = _step_command(s, b, commands)
            if c:
                spans.append((round(c["start"], 3), round(c["end"], 3)))
    return spans


def add_spans(keep: list, spans: list) -> list:
    """keep with spans added back, merged and in order."""
    parts = sorted([list(k) for k in keep] + [list(sp) for sp in spans])
    out = []
    for a, b in parts:
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def timer_scale(runs: list) -> float:
    """Seconds a full timer bar stands for: the longest timed run of the whole reel, rounded up, so bars in
    different scenes compare directly (CASE-D1.2). runs: seconds of every timed command."""
    import math
    return float(max(1, math.ceil(max(runs, default=10.0))))


def timed_runs(spec: dict, take: Path) -> list:
    """Seconds of each timed command in a scene's take."""
    ev = json.loads((Path(take) / "events.json").read_text())
    return [i["seconds"] for i in timer_items(spec.get("step", []), ev["beats"], ev.get("commands", []), 1.0)]


def captions_for(steps: list, beats: list) -> list:
    """One caption per step with `say`, shown until the next step with `say` starts: a step without it
    keeps the previous sentence on screen, so a muted viewer always has a caption (CASE-E3). A step with
    the `key` verb ends its caption with that key's keycap (CASE-B5)."""
    caps = []
    for s, b in zip(steps, beats):
        if s.get("say"):
            c = {"start": round(min(b["start"] + 0.2, b["end"] - 0.1), 3), "end": round(b["end"], 3), "text": s["say"]}
            caps.append(c)
        elif caps:
            caps[-1]["end"] = round(b["end"], 3)
        if s.get("key") and caps:
            caps[-1]["keys"] = str(s["key"]).lower()
    return caps


def timer_items(steps: list, beats: list, commands: list, scale: float) -> list:
    """One timer bar per step with `timer = "<label>"`, over its command's run (CASE-D1.2). Every bar
    shares `scale` seconds for its full width, so bars in different scenes compare directly."""
    items = []
    for s, b in zip(steps, beats):
        if s.get("type") and s.get("timer"):
            c = _step_command(s, b, commands)
            if c:
                items.append({"label": str(s["timer"]), "start": round(c["start"], 3), "end": round(c["end"], 3),
                              "seconds": round(c["end"] - c["start"], 1), "scale": float(scale), "row": len(items)})
    return items


def squeeze_spans(steps: list, beats: list, commands: list) -> list:
    """Stage spans to cut for steps marked `squeeze = true` (CASE-C3.3): the middle of the step's typed
    command while it runs (a page loading, a device booting), even though the screen moves, keeping
    SQUEEZE_KEEP after it starts, SQUEEZE_TAIL before it ends, and the step's narration."""
    spans = []
    for s, b in zip(steps, beats):
        if not (s.get("squeeze") and s.get("type")):
            continue
        c = _step_command(s, b, commands)
        if not c:
            continue
        lo = round(max(c["start"] + SQUEEZE_KEEP, b["start"] + 0.2 + b.get("narration", 0.0)), 3)
        hi = round(c["end"] - SQUEEZE_TAIL, 3)
        if hi - lo >= SQUEEZE_MIN:
            spans.append((lo, hi))
    return spans


def cut_spans(keep: list, spans: list) -> list:
    """keep minus spans: [[a, b], ...] in order."""
    out = []
    for a, b in keep:
        parts = [[a, b]]
        for lo, hi in spans:
            nxt = []
            for x, y in parts:
                if hi <= x or lo >= y:
                    nxt.append([x, y])
                    continue
                if lo > x:
                    nxt.append([x, lo])
                if hi < y:
                    nxt.append([hi, y])
            parts = nxt
        out += [p for p in parts if p[1] - p[0] > 0.05]
    return out


def plan(spec: dict, take: Path, edit: Path, scale: float = 10.0) -> Path:
    """edit/timeline.json from a scene's take (stage video + events.json) and its script."""
    take, edit = Path(take), Path(edit)
    edit.mkdir(parents=True, exist_ok=True)
    ev = json.loads((take / "events.json").read_text())
    if ev.get("device_sync"):
        from .record_terminal import composite_devices
        composite_devices(take, spec["accent"])  # rebuilt from the kept sources: layout changes need no new take
    st = {**ev["stage"], "path": str(take / ev["stage"]["path"])}
    regions = ev.get("regions", {})
    rect = lambda name: tuple(regions[name]) if name in regions else None
    act = motion.Activity.from_video(st["path"], st["width"], st["height"])
    if ev.get("kind") == "terminal" and ev.get("sync", {}).get("method") != "marks":
        ev = refine(ev, act)  # only without the on-screen marker: anchors are a rougher fallback

    steps = spec.get("step", [])
    if ev.get("kind") == "terminal":
        # The camera follows the script as it is now: focus is an editing field, changed without a new take.
        from .record_terminal import beat_focus
        noisy = [p["name"] for p in spec["pane"] if p.get("noisy")]
        for s, b in zip(steps, ev["beats"]):
            b["focus"] = beat_focus(s, spec["pane"])
            b["ignore"] = [n for n in noisy if n not in b["focus"]]
            b["full"] = b["focus"] in ([], ["full"])
    beats = []
    for b in ev["beats"]:
        beats.append(motion.Beat(
            start=b["start"], end=b["end"], label=b.get("label", ""),
            focus=[rect(n) for n in b.get("focus", []) if rect(n)] or list(map(tuple, b.get("focus_rects", []))),
            quiet_ignore=[rect(n) for n in b.get("ignore", []) if rect(n)],
            tight=ev.get("kind") == "terminal" and not b.get("full"),
            protect=b.get("narration", 0.0)))
    # Pages and windows are framed from what changed, cursor included: keep more context there.
    # A portrait phone already fills the stage's height; zooming in would cut it off.
    # A Mac window is already scaled to fill the stage; zooming cut off its toolbar and edges.
    max_zoom = {"terminal": motion.MAX_ZOOM, "ios": 1.0, "android": 1.0, "mac": 1.0}.get(ev.get("kind"), 1.6)
    cmds = ev.get("commands", [])
    if ev.get("kind") in ("animation", "card"):
        # Drawn full-frame and timed by their author: no camera moves, nothing cut.
        shots = [{"t": 0.0, "x": st["width"] / 2, "y": st["height"] / 2, "zoom": 1.0}]
        keep = [[0.0, st["duration"]]]
    else:
        shots, keep = motion.plan(beats, act, st["duration"], max_zoom)
        keep = cut_spans(keep, squeeze_spans(steps, ev["beats"], cmds))
        keep = add_spans(keep, keep_spans(steps, ev["beats"], cmds))

    data = {
        "stage": st,
        "output": {"width": 1920, "height": 1080, "fps": 30},
        "style": {"accent": spec["accent"], "kind": ev["kind"]},
        "keep": keep,
        "shots": shots,
        "captions": captions_for(steps, ev["beats"]),
    }
    timers = timer_items(steps, ev["beats"], cmds, scale)
    if timers:
        data["timers"] = timers
    # Narration: each step's synthesised sentence (cached clip), starting with its caption (see voice.py).
    narration = [{"wav": s["_narration_wav"], "start": round(b["start"] + 0.2, 3)}
                 for s, b in zip(steps, ev["beats"]) if spec.get("voice") and s.get("_narration_wav")]
    if narration:
        data["narration"] = narration
    path = edit / "timeline.json"
    timeline.save(data, path)
    return path


def sync_report(take: Path) -> list:
    """For each typed step: logged command start vs the first visible change in its pane (CASE-A2.1).
    A developer's check (scripts/dev.py sync); not part of reel make."""
    out = Path(take)
    ev = json.loads((out / "events.json").read_text())
    st = ev["stage"]
    act = motion.Activity.from_video(str(out / st["path"]), st["width"], st["height"])
    rows = []
    for c in ev.get("commands", []):
        region = ev["regions"].get(c["pane"])
        if not region:
            continue
        seen = act.first_change(c["start"] - 0.05, c["start"] + 3, tuple(region), min_pixels=4)
        rows.append({"pane": c["pane"], "cmd": c["cmd"], "logged": c["start"],
                     "seen": seen, "delta": None if seen is None else round(seen - c["start"], 3)})
    return rows


def framing_report(take: Path, edit: Path) -> list:
    """Per step: share of the changes (outside ignored panes) that fall inside the camera's view
    once it has arrived (CASE-A2). 1.0 means the camera saw everything that moved."""
    out = Path(take)
    ev = json.loads((out / "events.json").read_text())
    tl = timeline.load(Path(edit) / "timeline.json")
    st = ev["stage"]
    act = motion.Activity.from_video(str(out / st["path"]), st["width"], st["height"])
    regions = ev.get("regions", {})
    shots = tl["shots"]

    def view(t):
        cur = shots[0]
        for s in shots:
            if s["t"] <= t:
                cur = s
        hw, hh = st["width"] / cur["zoom"] / 2, st["height"] / cur["zoom"] / 2
        return (cur["x"] - hw, cur["y"] - hh, cur["x"] + hw, cur["y"] + hh)

    rows = []
    for b in ev["beats"]:
        ignore = [tuple(regions[n]) for n in b.get("ignore", []) if n in regions]
        t0 = b["start"] + motion.MOVE  # once the camera has arrived
        inside = total = 0
        for i in act._range(t0, b["end"]):
            if timeline.output_time(tl["keep"], i / act.fps) is None:
                continue  # cut from the film
            n = act.count(i, None, ignore)
            if n:
                total += n
                inside += act.count(i, view(i / act.fps), ignore)
        rows.append({"step": b.get("label"), "changed": total,
                     "inside_view": round(inside / total, 3) if total else None})
    return rows
