"""Records an iOS or Android app, on a simulator, an emulator or a real phone, driven by agent-device.

Scene fields for kind = "ios" or "android" (the table is named after the kind):

    [ios]
    app = "com.apple.Preferences"   # bundle id, package or app name, as agent-device open takes it
    device = "$REEL_SIM"            # the device's id (UDID or adb serial), usually an environment variable
                                    # the agent sets: the agent prepares the device, reel does not borrow one
    settle = true                   # wait for the UI to go quiet after each action (about 3 s on a
                                    # phone); false for apps that react at once, like a calculator

    [[step]]                        # one action per step
    click = "General"               # a ref, selector or visible label
    fill = ["selector", "text"]     # replace the text in an input
    type = "text"                   # type into the focused input
    key = "Enter"                   # the keyboard's return key (Enter or Return)
    scroll = "down"
    back = true
    wait = 'text="Done"'            # a selector that must appear (text=, label=, value=, id=)
    hold = 1.0
    say = "..."

The status bar shows 9:41, a full battery and full bars while recording, and is put back afterwards: on
an iOS simulator through simctl, on Android through the system UI's demo mode. A real iPhone's status
bar cannot be set: preflight reminds the user to turn on Do Not Disturb and pick screens without
personal data. On a real iPhone, agent-device's runner must be signed by your team: export the
AGENT_DEVICE_IOS_* variables agent-device documents (they stay out of the scene, which may be public).

agent-device draws a dot where each touch lands, so viewers see the taps; the camera shows the whole
phone. Android records only frames that change; the stage is rebuilt at a constant 30 fps.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from . import stage
from .preflight import device_id
from .record_terminal import RecordError

VERBS = ("click", "fill", "type", "key", "scroll", "back")


def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {}


def _is_simulator(udid: str) -> bool:
    r = subprocess.run(["xcrun", "simctl", "list", "devices"], capture_output=True, text=True)
    return udid in r.stdout


class _CleanStatusBar:
    """9:41, full battery and bars while recording; the device's own status bar again afterwards."""

    def __init__(self, platform: str, udid: str):
        self.platform, self.udid = platform, udid
        self.sim = platform == "ios" and _is_simulator(udid)

    def _adb(self, *a):
        subprocess.run(["adb", "-s", self.udid, "shell", *a], capture_output=True)

    def _demo(self, command: str, *extras):
        self._adb("am", "broadcast", "-a", "com.android.systemui.demo", "-e", "command", command, *extras)

    def __enter__(self):
        if self.sim:
            subprocess.run(["xcrun", "simctl", "status_bar", self.udid, "override", "--time", "9:41",
                            "--batteryState", "charged", "--batteryLevel", "100", "--cellularBars", "4",
                            "--wifiBars", "3"], capture_output=True)
        elif self.platform == "android":
            self._adb("settings", "put", "global", "sysui_demo_allowed", "1")
            self._demo("enter")
            self._demo("clock", "-e", "hhmm", "0941")
            self._demo("battery", "-e", "level", "100", "-e", "plugged", "false")
            self._demo("network", "-e", "wifi", "show", "-e", "level", "4", "-e", "fully", "true")
            self._demo("network", "-e", "mobile", "hide")  # an emulator's mobile signal reads a faint "3G"
            self._demo("notifications", "-e", "visible", "false")
        return self

    def __exit__(self, *exc):
        if self.sim:
            subprocess.run(["xcrun", "simctl", "status_bar", self.udid, "clear"], capture_output=True)
        elif self.platform == "android":
            self._demo("exit")


def record(spec: dict, out: Path, rehearse: bool = False) -> Path | None:
    """Records stage.mp4 and events.json into out; with rehearse, runs the steps once without recording."""
    platform = spec["kind"]
    block = spec[platform]
    udid = device_id(block["device"])
    if not udid or "$" in udid:
        raise RecordError(f"[{platform}] device {block['device']!r} is not set")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw.mp4"
    session = f"reel{os.getpid()}"
    pick = "--udid" if platform == "ios" else "--serial"  # an iOS UDID, an Android adb serial
    ad = lambda *a: subprocess.run(
        ["agent-device", *map(str, a), pick, udid, "--session", session, "--platform", platform, "--json"],
        capture_output=True, text=True)
    beats, taps = [], []
    with _CleanStatusBar(platform, udid):
        try:
            r = ad("open", block["app"], "--foreground")
            if r.returncode != 0:
                raise RecordError(f"agent-device open {block['app']}: {(r.stderr or r.stdout).strip()[-400:]}")
            time.sleep(1.0)
            if not rehearse:
                r = ad("record", "start", raw)
                if r.returncode != 0:
                    raise RecordError(f"agent-device record start: {(r.stderr or r.stdout).strip()[-400:]}")
            t0 = time.monotonic()
            time.sleep(1.2)
            for i, s in enumerate(spec["step"], 1):
                start = time.monotonic() - t0
                verb = next((v for v in VERBS if v in s), None)
                if verb:
                    args = _args(verb, s[verb])
                    settle = block.get("settle", True) and verb in ("click", "fill", "scroll", "back")
                    r = ad(*args, *(["--settle"] if settle else []))
                    if r.returncode != 0:
                        raise RecordError(f"step {i}: agent-device {' '.join(map(str, args))}: "
                                          f"{(r.stderr or r.stdout).strip()[-400:]}")
                    point = _find_point(_last_json(r.stdout))
                    if point:
                        taps.append({"t": round(time.monotonic() - t0, 3), "x": point[0], "y": point[1], "step": i})
                if s.get("wait"):
                    r = ad("wait", s["wait"])
                    if r.returncode != 0:
                        raise RecordError(f"step {i}: waited for {s['wait']!r}: {(r.stderr or r.stdout).strip()[-400:]}")
                # Hold at least until the step's narration has been spoken (CASE-B7.1).
                spoken = s.get("_narration", 0.0) + 0.3 - (time.monotonic() - t0 - start)
                time.sleep(max(float(s.get("hold", 1.0)), spoken) if not rehearse else 0.3)
                beats.append({"start": round(start, 3), "label": f"step {i}", "narration": s.get("_narration", 0.0)})
            if not rehearse:
                r = ad("record", "stop")
                if r.returncode != 0:
                    raise RecordError(f"agent-device record stop: {(r.stderr or r.stdout).strip()[-400:]}")
        finally:
            ad("close")
    if rehearse:
        return None
    if not raw.exists():
        raise RecordError("agent-device wrote no video")
    lay = stage.build(raw, out / "stage.mp4", platform, spec["accent"])
    lay["accent"] = spec["accent"]
    dur = stage._probe(out / "stage.mp4")[2]
    for i, b in enumerate(beats):
        b["end"] = beats[i + 1]["start"] if i + 1 < len(beats) else round(dur, 3)
        b["focus"], b["ignore"] = [], []
    x, y, w, h = lay["hole"]
    events = {"kind": platform, "stage": {"path": "stage.mp4", "width": stage.W, "height": stage.H,
                                          "duration": dur, "fps": stage.FPS},
              "regions": {"full": [0, 0, stage.W, stage.H], "screen": [x, y, x + w, y + h]},
              "beats": beats, "taps": taps, "layout": lay}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path


def _args(verb: str, value) -> list:
    """agent-device's command for a step's verb."""
    if verb == "back":
        return ["back"]
    if verb == "key":
        if str(value).lower() not in ("enter", "return"):
            raise RecordError(f"key {value!r}: a phone's keyboard can only press Enter (Return)")
        return ["keyboard", "enter"]
    return [verb, *(value if isinstance(value, list) else [value])]


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
