"""Records a web page with agent-browser, in a browser session of its own, closed afterwards.

Scene fields for kind = "web":

    [web]
    url = "http://127.0.0.1:8765/"  # the page, served by the agent before reel make; the window's address bar
                                    # shows its host

    [[step]]                        # one action per step, run with agent-browser
    click = "selector or @ref"
    fill = ["selector", "text"]
    type = ["selector", "text"]     # real keystrokes into that element ("text" alone: the focused one;
                                    # while recording, a click may not move focus, so prefer the selector)
    key = "Enter"                   # a key, shown as a keycap after the caption
    scroll = "down 400"
    wait = "selector or ms"         # before the step ends
    hold = 1.0
    say = "..."

The page is 1600x900 CSS pixels at the browser's own device scale (emulating a scale switches
agent-browser to screenshots, which drop frames and once mixed frame sizes). A large, gliding cursor with
click ripples is drawn into the page (assets/cursor.js). The camera follows what changes on the page.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from . import stage
from .record_terminal import RecordError

VERBS = ("click", "fill", "type", "key", "scroll")
VIEWPORT = (1600, 900)
CURSOR_JS = Path(__file__).resolve().parent / "assets" / "cursor.js"


def record(spec: dict, out: Path, rehearse: bool = False) -> Path | None:
    """Records stage.mp4 and events.json into out; with rehearse, runs the steps once without recording."""
    web = spec["web"]
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    session = f"reel{os.getpid()}"
    ab = lambda *a, check=True: subprocess.run(["agent-browser", "--session", session, *map(str, a)],
                                               capture_output=True, text=True, check=check)
    raw = out / "raw.mp4"
    beats, steps = [], spec["step"]
    try:
        ab("set", "viewport", *VIEWPORT)
        # Our own large, gliding cursor with click ripples (Screen Studio-like), not agent-browser's small one.
        r = ab("--init-script", CURSOR_JS, "open", web["url"], check=False)
        if r.returncode != 0:
            raise RecordError(f"agent-browser open {web['url']}: {(r.stderr or r.stdout).strip()[-300:]} "
                              "(is the page served?)")
        ab("wait", "1000")
        if not rehearse:
            ab("record", "start", raw)
        t0 = time.monotonic()
        time.sleep(1.2)  # the page as it is, before anything happens
        for i, s in enumerate(steps, 1):
            start = time.monotonic() - t0
            verb = next((v for v in VERBS if v in s), None)
            if verb:
                v = s[verb]
                args = v if isinstance(v, list) else str(v).split(" ", 1) if verb == "scroll" else [v]
                cmd = ["keyboard", "type"] if verb == "type" and len(args) == 1 else ["press"] if verb == "key" else [verb]
                r = ab(*cmd, *args, check=False)
                if r.returncode != 0:
                    raise RecordError(f"step {i}: agent-browser {' '.join(cmd)} {args}: {(r.stderr or r.stdout).strip()}")
            if s.get("wait"):
                r = ab("wait", s["wait"], check=False)
                if r.returncode != 0:
                    raise RecordError(f"step {i}: waited for {s['wait']!r}: {(r.stderr or r.stdout).strip()}")
            # Hold at least until the step's narration has been spoken (CASE-B7.1).
            spoken = s.get("_narration", 0.0) + 0.3 - (time.monotonic() - t0 - start)
            time.sleep(max(float(s.get("hold", 1.0)), spoken) if not rehearse else 0.3)
            beats.append({"start": round(start, 3), "label": f"step {i}", "narration": s.get("_narration", 0.0)})
        if not rehearse:
            r = ab("record", "stop", check=False)
            if r.returncode != 0:  # seen once: the first stop fails, a second one saves
                time.sleep(1.0)
                r = ab("record", "stop", check=False)
            if r.returncode != 0:
                raise RecordError(f"agent-browser record stop: {(r.stderr or r.stdout).strip()}")
    finally:
        ab("close", check=False)
    if rehearse:
        return None

    lay = stage.build(raw, out / "stage.mp4", "web", spec["accent"], urlparse(web["url"]).netloc)
    lay["accent"] = spec["accent"]
    dur = stage._probe(out / "stage.mp4")[2]
    for i, b in enumerate(beats):
        b["end"] = beats[i + 1]["start"] if i + 1 < len(beats) else round(dur, 3)
        b["focus"], b["ignore"] = [], []
    x, y, w, h = lay["hole"]
    events = {"kind": "web", "stage": {"path": "stage.mp4", "width": stage.W, "height": stage.H,
                                        "duration": dur, "fps": stage.FPS},
              "regions": {"full": [0, 0, stage.W, stage.H], "page": [x, y, x + w, y + h]},
              "beats": beats, "layout": lay}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path
