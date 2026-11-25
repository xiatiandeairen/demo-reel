"""Records one Mac app window: agent-desktop drives the app, screencapture records only that window's rectangle.

Scene fields for kind = "mac":

    [mac]
    app = "TextEdit"            # its window is brought to the front; the agent opens it before reel make

    [[step]]                    # one action per step, run with agent-desktop
    click = "button:Save"       # target: "role" or "role:name", resolved to a fresh ref each step
    type = ["textfield", "text"]  # typed one key at a time (45 ms each), so viewers see it
    key = "cmd+n"               # a key or combination, shown as a keycap
    wait = "role:text"          # must appear within 30 s before the step ends
    hold = 1.0
    say = "..."

Needs: an awake, unlocked display (macOS records nothing otherwise), and Screen Recording
permission for the app that runs reel (System Settings > Privacy & Security > Screen Recording).
The window is recorded where it is, so the demo app's window must not be covered. screencapture cannot
be stopped early, so its length is worked out from the steps' holds and narration beforehand.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import stage
from .record_terminal import RecordError

TYPING_MS = 45
WAIT_LIMIT = 30.0
VERBS = ("click", "type", "key")


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


def _wait(app: str, target: str, i: int) -> None:
    """Polls until target shows up in the app, up to WAIT_LIMIT seconds."""
    deadline = time.monotonic() + WAIT_LIMIT
    while True:
        try:
            _ref(app, target)
            return
        except RecordError:
            if time.monotonic() > deadline:
                raise RecordError(f"step {i}: {target!r} did not appear within {WAIT_LIMIT:.0f} s")
            time.sleep(0.5)


def capture_seconds(steps: list) -> int:
    """How long screencapture records: every step's hold (or narration), a margin for the action
    itself, and the opening."""
    return int(3 + 1.2 + sum(max(float(s.get("hold", 1.0)), s.get("_narration", 0.0) + 0.3) + 2.5 for s in steps))


def record(spec: dict, out: Path, rehearse: bool = False) -> Path | None:
    """Records stage.mp4 and events.json into out; with rehearse, runs the steps once without recording."""
    mac = spec["mac"]
    for i, s in enumerate(spec["step"], 1):
        bad = [v for v in ("fill", "scroll", "back") if v in s]
        if bad:
            raise RecordError(f"step {i}: a Mac window takes click, type and key, not {', '.join(bad)}")
    if not _ad("list-displays").get("data"):
        raise RecordError("no active display: wake and unlock the Mac, then record again")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Bring the agent's window to the front. Not `launch`: reopening TextEdit (and other document apps)
    # puts its Open panel in front, home folder name and all (2026-11-25).
    d = _ad("focus-window", "--app", mac["app"])
    if not d.get("ok"):
        raise RecordError(f"no {mac['app']} window to bring to the front ({d.get('error')}): "
                          "open the window the steps act in before reel make")
    time.sleep(0.8)
    b = _focused_window(mac["app"])["bounds"]
    rect = f"{int(b['x'])},{int(b['y'])},{int(b['width'])},{int(b['height'])}"  # points, as screencapture takes
    raw_mov = out / "raw.mov"
    raw_mov.unlink(missing_ok=True)
    limit = capture_seconds(spec["step"])
    cap = None if rehearse else subprocess.Popen(
        ["screencapture", "-v", "-x", "-V", str(limit), f"-R{rect}", str(raw_mov)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t0 = time.monotonic()
    time.sleep(1.2)
    beats = []
    try:
        for i, s in enumerate(spec["step"], 1):
            start = time.monotonic() - t0
            verb = next((v for v in VERBS if v in s), None)
            if verb:
                args = list(s[verb]) if isinstance(s[verb], list) else [s[verb]]
                if verb in ("click", "type"):
                    args[0] = _ref(mac["app"], args[0])
                if verb == "type":
                    args += ["--interval-ms", str(TYPING_MS)]
                # --headed: real key and mouse events, as a person makes them (agent-desktop's default,
                # headless semantic delivery, refuses a text area that only takes focus and keystrokes).
                d = _ad("press" if verb == "key" else verb, *args, "--headed")
                if not d.get("ok"):
                    raise RecordError(f"step {i}: agent-desktop {verb} {args}: {d.get('error')}")
            if s.get("wait"):
                _wait(mac["app"], s["wait"], i)
            # Hold at least until the step's narration has been spoken (CASE-B7.1).
            spoken = s.get("_narration", 0.0) + 0.3 - (time.monotonic() - t0 - start)
            time.sleep(max(float(s.get("hold", 1.0)), spoken) if not rehearse else 0.3)
            beats.append({"start": round(start, 3), "label": f"step {i}", "narration": s.get("_narration", 0.0)})
        used = time.monotonic() - t0
    finally:
        # screencapture stops at -V seconds; it ignores signals while recording.
        if cap:
            try:
                cap.wait(timeout=limit + 30)
            except subprocess.TimeoutExpired:
                cap.kill()
                raise RecordError("screencapture did not finish; does the app running reel have Screen Recording permission?")
    if rehearse:
        return None
    if not raw_mov.exists():
        raise RecordError(f"screencapture wrote no video: {cap.stderr.read().decode().strip()}")
    raw = out / "raw.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw_mov), "-t", f"{used + 0.3:.2f}",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(raw)], check=True)
    raw_mov.unlink()

    lay = stage.build(raw, out / "stage.mp4", "mac", spec["accent"])
    lay["accent"] = spec["accent"]
    dur = stage._probe(out / "stage.mp4")[2]
    for i, bt in enumerate(beats):
        bt["end"] = beats[i + 1]["start"] if i + 1 < len(beats) else round(dur, 3)
        bt["focus"], bt["ignore"] = [], []
    x, y, w, h = lay["hole"]
    events = {"kind": "mac", "stage": {"path": "stage.mp4", "width": stage.W, "height": stage.H,
                                        "duration": dur, "fps": stage.FPS},
              "regions": {"full": [0, 0, stage.W, stage.H], "window": [x, y, x + w, y + h]},
              "beats": beats, "layout": lay}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path
