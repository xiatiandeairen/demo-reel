"""Records one Mac app window: agent-desktop drives the app, screencapture records only that window's rectangle.

Spec fields for kind = "mac":

    [mac]
    app = "TextEdit"
    launch_args = []            # optional, passed to the app
    max_seconds = 60            # upper bound for the recording; it is trimmed afterwards
    typing_ms = 45
    prepare = ["cmd+n"]         # key combos pressed before recording starts, e.g. a new document,
                                # so the window that gets recorded is the one the steps act in

    [[step]]                    # one action per step, run with agent-desktop
    click = "button:Save"       # target: "role" or "role:name", resolved to a fresh ref each step
    type = ["textfield", "text"]  # typed one key at a time (typing_ms), so viewers see it
    press = "cmd+n"
    wait = "role:text"          # must appear before the step ends
    hold = 1.0
    caption = "..."

Needs: an awake, unlocked display (macOS records nothing otherwise), and Screen Recording
permission for the app that runs reel (System Settings > Privacy & Security > Screen Recording).
The window is recorded where it is, so the demo app's window must not be covered.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import stage
from .record_terminal import RecordError, _slug


def _ad(*args) -> dict:
    r = subprocess.run(["agent-desktop", *map(str, args)], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"ok": False, "error": {"message": (r.stderr or r.stdout).strip()}}
    return d


def _ref(app: str, target: str) -> str:
    """agent-desktop acts on snapshot refs (@<snapshot>:eN); find one for "role" or "role:name"."""
    if target.startswith("@"):
        return target
    role, _, name = target.partition(":")
    d = _ad("find", "--app", app, "--role", role, *(["--name", name] if name else []))
    matches = (d.get("data") or {}).get("matches") or []
    if not d.get("ok") or not matches:
        raise RecordError(f"no {target!r} in {app}: {d.get('error') or 'no match'}")
    focused = [m for m in matches if "focused" in (m.get("states") or [])]
    return (focused or matches)[0]["ref_id"]


def _focused_window(app: str) -> dict:
    """The app's front window: the focused one, else the last listed (front-most on macOS)."""
    d = _ad("list-windows", "--app", app)
    wins = [w for w in d.get("data", []) if w.get("visible") and not w.get("minimized")]
    if not wins:
        raise RecordError(f"no visible {app} window")
    focused = [w for w in wins if w.get("is_focused")]
    return (focused or wins[:1])[0]


def record(spec: dict, out: Path) -> Path:
    mac = spec.get("mac", {})
    if "app" not in mac:
        raise RecordError("[mac] needs app")
    if not _ad("list-displays").get("data"):
        raise RecordError("no active display: wake and unlock the Mac, then record again")
    out = Path(out).resolve()
    work = Path(f"/tmp/reel-{_slug(spec['title'])}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    d = _ad("launch", mac["app"], "--activate", *[f"--arg={a}" for a in mac.get("launch_args", [])])
    if not d.get("ok"):
        raise RecordError(f"launch {mac['app']}: {d.get('error')}")
    time.sleep(1.0)
    for keys in mac.get("prepare", []):
        d = _ad("press", keys)
        if not d.get("ok"):
            raise RecordError(f"prepare {keys}: {d.get('error')}")
        time.sleep(0.8)
    b = _focused_window(mac["app"])["bounds"]
    rect = f"{int(b['x'])},{int(b['y'])},{int(b['width'])},{int(b['height'])}"  # points, as screencapture takes
    raw_mov = work / "raw.mov"
    limit = int(mac.get("max_seconds", 60))
    cap = subprocess.Popen(["screencapture", "-v", "-x", "-V", str(limit), f"-R{rect}", str(raw_mov)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t0 = time.monotonic()
    time.sleep(1.2)
    beats = []
    try:
        for i, s in enumerate(spec["step"], 1):
            start = time.monotonic() - t0
            for a in ("click", "type", "press"):
                if a in s:
                    args = list(s[a]) if isinstance(s[a], list) else [s[a]]
                    if a in ("click", "type"):
                        args[0] = _ref(mac["app"], args[0])
                    if a == "type":
                        args += ["--interval-ms", str(mac.get("typing_ms", 45))]
                    d = _ad(a, *args)
                    if not d.get("ok"):
                        raise RecordError(f"step {i}: agent-desktop {a} {args}: {d.get('error')}")
            if s.get("wait"):
                try:
                    _ref(mac["app"], s["wait"])
                except RecordError:
                    raise RecordError(f"step {i}: {s['wait']!r} did not appear")
            # Hold at least until the step's narration has been spoken (CASE-B7.1).
            spoken = s.get("_narration", 0.0) + 0.3 - (time.monotonic() - t0 - start)
            time.sleep(max(float(s.get("hold", 1.0)), spoken))
            beats.append({"start": round(start, 3), "label": f"step {i}", "caption": s.get("caption"),
                          "narration": s.get("_narration", 0.0)})
        used = time.monotonic() - t0
    finally:
        # screencapture stops at -V seconds; it ignores signals while recording.
        try:
            cap.wait(timeout=limit + 30)
        except subprocess.TimeoutExpired:
            cap.kill()
            raise RecordError("screencapture did not finish; does the app running reel have Screen Recording permission?")
    if not raw_mov.exists():
        raise RecordError(f"screencapture wrote no video: {cap.stderr.read().decode().strip()}")
    raw = work / "raw.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw_mov), "-t", f"{used + 0.3:.2f}",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(raw)], check=True)

    lay = stage.build(raw, out / "stage.mp4", "mac", spec["accent"])
    dur = stage._probe(out / "stage.mp4")[2]
    for i, bt in enumerate(beats):
        bt["end"] = beats[i + 1]["start"] if i + 1 < len(beats) else round(dur, 3)
        bt["focus"], bt["ignore"] = [], []
    x, y, w, h = lay["hole"]
    events = {"kind": "mac", "stage": {"path": "stage.mp4", "width": stage.W, "height": stage.H,
                                        "duration": dur, "fps": stage.FPS},
              "regions": {"full": [0, 0, stage.W, stage.H], "window": [x, y, x + w, y + h]},
              "window_points": b, "beats": beats, "layout": lay}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path
