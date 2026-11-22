"""Records a web page with agent-browser in a browser session borrowed from aq.

Spec fields for kind = "web":

    [web]
    workdir = "/tmp/reel-todomvc"   # default /tmp/reel-<title>; wiped before recording
    setup = "setup.sh"              # bash setup.sh <workdir>, before recording
    serve = "python3 -m http.server 8765"   # optional: started in <workdir>, stopped afterwards
    url = "http://localhost:8765/"
    label = "todomvc.com"           # text in the window's address bar (default: the url's host)
    viewport = [1600, 900]          # CSS pixels; frames come at the browser's own device scale
                                    # (emulating a scale switches agent-browser to screenshots,
                                    # which drop frames and once mixed frame sizes)

    [[step]]                        # one action per step, run with agent-browser
    click = "selector or @ref"
    fill = ["selector", "text"]
    type = ["selector", "text"]     # real keystrokes into that element ("text" alone: the focused one;
                                    # while recording, a click may not move focus, so prefer the selector)
    press = "Enter"
    hover = "selector"
    scroll = "down 400"
    wait = "selector or ms"         # before the step ends
    hold = 1.0
    caption = "..."

The camera follows what changes on the page during each step (no pane names on the web).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from . import stage
from .record_terminal import RecordError, _slug

ACTIONS = ("click", "fill", "type", "press", "hover", "scroll")


def _hold_browser() -> tuple:
    r = subprocess.run(["aq", "hold", "browser"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RecordError(f"aq hold browser failed: {r.stdout or r.stderr}")
    while d.get("status") == "waiting":
        r = subprocess.run(["aq", "status", d["id"], "--wait", "60"], capture_output=True, text=True)
        d = json.loads(r.stdout.strip().splitlines()[-1])
    if d.get("status") != "held":
        raise RecordError(f"aq hold browser: {d}")
    return d["id"], d["devices"][0]["id"]


def record(spec: dict, out: Path) -> Path:
    web = spec.get("web", {})
    if "url" not in web:
        raise RecordError("[web] needs url")
    out = Path(out).resolve()
    work = Path(web.get("workdir", f"/tmp/reel-{_slug(spec['title'])}"))
    if not str(work.resolve()).startswith(("/tmp/", "/private/tmp/")):
        raise RecordError(f"workdir must be under /tmp, since it is wiped before each recording: {work}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = {**os.environ, "REEL_WORK": str(work)}
    if web.get("setup"):
        subprocess.run(["bash", str(Path(spec["_dir"]) / web["setup"]), str(work)], check=True, env=env, cwd=spec["_dir"])
    server = None
    if web.get("serve"):
        server = subprocess.Popen(web["serve"], shell=True, cwd=work, env=env, start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)

    hold_id, session = _hold_browser()
    ab = lambda *a, check=True: subprocess.run(["agent-browser", "--session", session, *map(str, a)],
                                               capture_output=True, text=True, check=check)
    raw = work / "raw.mp4"
    beats, steps = [], spec["step"]
    try:
        vw, vh = web.get("viewport", [1600, 900])
        ab("set", "viewport", vw, vh)
        ab("open", web["url"])
        ab("wait", "1000")
        ab("record", "start", raw, "--cursor")
        t0 = time.monotonic()
        time.sleep(1.2)  # the page as it is, before anything happens
        for i, s in enumerate(steps, 1):
            start = time.monotonic() - t0
            for a in ACTIONS:
                if a in s:
                    args = s[a] if isinstance(s[a], list) else str(s[a]).split(" ", 1) if a == "scroll" else [s[a]]
                    cmd = ["keyboard", "type"] if a == "type" and len(args) == 1 else [a]
                    r = ab(*cmd, *args, check=False)
                    if r.returncode != 0:
                        raise RecordError(f"step {i}: agent-browser {a} {args}: {(r.stderr or r.stdout).strip()}")
            if s.get("wait"):
                r = ab("wait", s["wait"], check=False)
                if r.returncode != 0:
                    raise RecordError(f"step {i}: waited for {s['wait']!r}: {(r.stderr or r.stdout).strip()}")
            time.sleep(float(s.get("hold", 1.0)))
            beats.append({"start": round(start, 3), "label": f"step {i}", "caption": s.get("caption")})
        r = ab("record", "stop", check=False)
        if r.returncode != 0:  # seen once: the first stop fails, a second one saves
            time.sleep(1.0)
            r = ab("record", "stop", check=False)
        if r.returncode != 0:
            raise RecordError(f"agent-browser record stop: {(r.stderr or r.stdout).strip()}")
    finally:
        subprocess.run(["aq", "release", hold_id], capture_output=True)
        if server:
            os.killpg(server.pid, signal.SIGTERM)
        if web.get("teardown"):
            subprocess.run(["bash", str(Path(spec["_dir"]) / web["teardown"]), str(work)], env=env, cwd=spec["_dir"])

    label = web.get("label") or urlparse(web["url"]).netloc
    lay = stage.build(raw, out / "stage.mp4", "web", spec["accent"], label)
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
