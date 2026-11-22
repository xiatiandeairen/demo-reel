"""An animation scene: an HTML page with CSS animations, rendered frame by frame.

Spec fields for kind = "animation":

    [animation]
    html = "problem.html"   # next to the spec; 1920x1080, animated with CSS (or Web Animations)
    seconds = 6
    fps = 30

    [[step]]                # optional narration
    at = 0.4
    say = "Three agents. One Mac."

How it renders: a browser plays animations on its own clock, so a screenshot lands at no exact
time. Every frame pauses all of the page's animations and sets each one's currentTime to that
frame's moment (n / fps), then takes a screenshot; frame n is exactly time n / fps, however fast
the machine is. The browser is borrowed from aq and driven with agent-browser.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .record_card import H, W, write_events
from .record_terminal import RecordError
from .record_web import _hold_browser


def frame_js(n: int, fps: int) -> str:
    ms = round(n * 1000 / fps, 3)
    return f"document.getAnimations().forEach(a => {{ a.pause(); a.currentTime = {ms}; }}); {ms}"


def record(spec: dict, out: Path) -> Path:
    anim = spec.get("animation", {})
    if "html" not in anim:
        raise RecordError("[animation] needs html")
    page = (Path(spec["_dir"]) / anim["html"]).resolve()
    if not page.exists():
        raise RecordError(f"[animation] html not found: {page}")
    seconds, fps = float(anim.get("seconds", 6)), int(anim.get("fps", 30))
    frames = round(seconds * fps)
    out = Path(out)
    hold_id, session = _hold_browser()
    ab = lambda *a: subprocess.run(["agent-browser", "--session", session, *map(str, a)],
                                   capture_output=True, text=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for args in (("set", "viewport", W, H), ("open", page.as_uri())):
                r = ab(*args)
                if r.returncode != 0:
                    raise RecordError(f"agent-browser {args[0]}: {(r.stderr or r.stdout).strip()}")
            for n in range(frames):
                r = ab("eval", frame_js(n, fps))
                shot = ab("screenshot", f"{tmp}/f{n:05d}.png")
                if r.returncode != 0 or shot.returncode != 0:
                    raise RecordError(f"frame {n}: {(r.stderr or shot.stderr or r.stdout).strip()}")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", f"{tmp}/f%05d.png",
                            "-vf", f"scale={W}:{H}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                            str(out / "stage.mp4")], check=True)
    finally:
        subprocess.run(["aq", "release", hold_id], capture_output=True)
    return write_events(out, "animation", seconds, spec.get("step", []))
