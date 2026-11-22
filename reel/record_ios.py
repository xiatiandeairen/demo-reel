"""Records an iOS app on a simulator or an iPhone borrowed from aq, driven by agent-device.

Spec fields for kind = "ios":

    [ios]
    app = "com.apple.Preferences"   # bundle id or app name, as agent-device open takes it
    device = "simulator"            # or "physical": an iPhone registered in aq's [ios-device] ids
    status_bar = true               # simulator only: 9:41, full battery and bars
    settle = true                   # wait for the UI to go quiet after each action (about 3 s on a
                                    # phone); false for apps that react at once, like a calculator

On a physical iPhone, agent-device's runner must be signed by your team: export the
AGENT_DEVICE_IOS_* variables agent-device documents before running reel (they stay out of the
spec, which may be public). The phone must be unlocked, with Settings > Developer > Enable UI
Automation on. Pick an app and flow that show no personal data: status bar, account names and
notifications are recorded as they are.

    [[step]]                        # one action per step, run with agent-device
    press = "General"               # a ref, selector or visible label
    fill = ["selector", "text"]
    type = "text"
    scroll = "down"
    back = true
    wait = 'text="Done"'             # a selector that must appear (text=, label=, value=, id=)
    hold = 1.0
    caption = "..."

agent-device draws a dot where each touch lands, so viewers see the taps; the camera follows
what changes on screen during each step.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import stage
from .record_terminal import RecordError, _slug


def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {}


def _hold(kind: str) -> tuple:
    r = subprocess.run(["aq", "hold", kind], capture_output=True, text=True)
    d = _last_json(r.stdout)
    while d.get("status") == "waiting":
        d = _last_json(subprocess.run(["aq", "status", d["id"], "--wait", "60"], capture_output=True, text=True).stdout)
    if d.get("status") != "held":
        raise RecordError(f"aq hold {kind}: {d.get('message') or r.stdout or r.stderr}")
    return d["id"], d["devices"][0]["id"]


def record(spec: dict, out: Path) -> Path:
    ios = spec.get("ios", {})
    if "app" not in ios:
        raise RecordError("[ios] needs app")
    out = Path(out).resolve()
    work = Path(f"/tmp/reel-{_slug(spec['title'])}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    raw = work / "raw.mp4"
    physical = ios.get("device", "simulator") == "physical"
    hold_id, udid = _hold("ios-device" if physical else "ios-sim")
    session = f"reel{os.getpid()}"
    ad = lambda *a, check=False: subprocess.run(
        ["agent-device", *map(str, a), "--udid", udid, "--session", session, "--platform", "ios", "--json"],
        capture_output=True, text=True, check=check)
    beats, taps = [], []
    try:
        if not physical and ios.get("status_bar", True):
            subprocess.run(["xcrun", "simctl", "status_bar", udid, "override", "--time", "9:41",
                            "--batteryState", "charged", "--batteryLevel", "100", "--cellularBars", "4",
                            "--wifiBars", "3"], capture_output=True)
        r = ad("open", ios["app"], "--foreground")
        if r.returncode != 0:
            raise RecordError(f"agent-device open {ios['app']}: {(r.stderr or r.stdout).strip()[-400:]}")
        time.sleep(1.0)
        r = ad("record", "start", raw)
        if r.returncode != 0:
            raise RecordError(f"agent-device record start: {(r.stderr or r.stdout).strip()[-400:]}")
        t0 = time.monotonic()
        time.sleep(1.2)
        for i, s in enumerate(spec["step"], 1):
            start = time.monotonic() - t0
            for a in ("press", "fill", "type", "scroll", "back"):
                if a not in s:
                    continue
                args = [] if a == "back" else s[a] if isinstance(s[a], list) else [s[a]]
                settle = ios.get("settle", True) and a != "type"
                r = ad(a, *args, *(["--settle"] if settle else []))
                if r.returncode != 0:
                    raise RecordError(f"step {i}: agent-device {a} {args}: {(r.stderr or r.stdout).strip()[-400:]}")
                d = _last_json(r.stdout)
                point = _find_point(d)
                if point:
                    taps.append({"t": round(time.monotonic() - t0, 3), "x": point[0], "y": point[1], "step": i})
            if s.get("wait"):
                r = ad("wait", s["wait"])
                if r.returncode != 0:
                    raise RecordError(f"step {i}: waited for {s['wait']!r}: {(r.stderr or r.stdout).strip()[-400:]}")
            time.sleep(float(s.get("hold", 1.0)))
            beats.append({"start": round(start, 3), "label": f"step {i}", "caption": s.get("caption")})
        r = ad("record", "stop")
        if r.returncode != 0:
            raise RecordError(f"agent-device record stop: {(r.stderr or r.stdout).strip()[-400:]}")
    finally:
        ad("close")
        subprocess.run(["aq", "release", hold_id], capture_output=True)

    if not raw.exists():
        raise RecordError("agent-device wrote no video")
    lay = stage.build(raw, out / "stage.mp4", "ios", spec["accent"])
    dur = stage._probe(out / "stage.mp4")[2]
    for i, b in enumerate(beats):
        b["end"] = beats[i + 1]["start"] if i + 1 < len(beats) else round(dur, 3)
        b["focus"], b["ignore"] = [], []
    x, y, w, h = lay["hole"]
    events = {"kind": "ios", "stage": {"path": "stage.mp4", "width": stage.W, "height": stage.H,
                                        "duration": dur, "fps": stage.FPS},
              "regions": {"full": [0, 0, stage.W, stage.H], "screen": [x, y, x + w, y + h]},
              "beats": beats, "taps": taps, "layout": lay}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path


def _find_point(d):
    """A touch point from agent-device's JSON, if it reports one (keys vary by command)."""
    stack = [d]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if isinstance(cur.get("x"), (int, float)) and isinstance(cur.get("y"), (int, float)):
                return cur["x"], cur["y"]
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None
