"""An animation scene: an HTML page with CSS animations, rendered frame by frame.

Scene fields for kind = "animation":

    [animation]
    html = "problem.html"   # next to the scene; 1920x1080, animated with CSS (or Web Animations)

    [[step]]                # optional narration: the first sentence 0.4 s in, each next one after the last
    say = "Three agents. One Mac."

How long it runs follows from the page: the end of its last animation (give every animation `both`, so
it rests on its first and last frames), or the end of the narration if that is later.

How it renders: a browser plays animations on its own clock, so a screenshot lands at no exact
time. Every frame pauses all of the page's animations and sets each one's currentTime to that
frame's moment (n / 30), then takes a screenshot; frame n is exactly time n / 30, however fast
the machine is. A headless browser session of agent-browser's own does it and is closed afterwards.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .record_card import GAP, LEAD_IN, READ_BASE, H, W, write_events
from .record_terminal import RecordError

FPS = 30
END_JS = ("Math.max(0, ...document.getAnimations().map(a => a.effect.getComputedTiming().endTime)"
          ".filter(Number.isFinite))")


def frame_js(n: int, fps: int) -> str:
    ms = round(n * 1000 / fps, 3)
    return f"document.getAnimations().forEach(a => {{ a.pause(); a.currentTime = {ms}; }}); {ms}"


def record(spec: dict, out: Path, rehearse: bool = False) -> Path | None:
    anim = spec["animation"]
    page = (Path(spec["_dir"]) / anim["html"]).resolve()
    if not page.exists():
        raise RecordError(f"[animation] html not found: {page}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    session = f"reel-anim{os.getpid()}"
    ab = lambda *a: subprocess.run(["agent-browser", "--session", session, *map(str, a)],
                                   capture_output=True, text=True)
    try:
        for args in (("set", "viewport", W, H), ("open", page.as_uri())):
            r = ab(*args)
            if r.returncode != 0:
                raise RecordError(f"agent-browser {args[0]}: {(r.stderr or r.stdout).strip()}")
        r = ab("eval", END_JS)
        try:
            ends = float(r.stdout.strip().splitlines()[-1]) / 1000
        except (ValueError, IndexError):
            raise RecordError(f"could not read the page's animations: {(r.stderr or r.stdout).strip()[-200:]}")
        spoken = LEAD_IN + sum((s.get("_narration") or READ_BASE) + GAP for s in spec.get("step", []))
        seconds = round(max(ends, spoken, 1.0), 2)
        if rehearse:
            return None
        frames = round(seconds * FPS)
        with tempfile.TemporaryDirectory() as tmp:
            for n in range(frames):
                r = ab("eval", frame_js(n, FPS))
                shot = ab("screenshot", f"{tmp}/f{n:05d}.png")
                if r.returncode != 0 or shot.returncode != 0:
                    raise RecordError(f"frame {n}: {(r.stderr or shot.stderr or r.stdout).strip()}")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", f"{tmp}/f%05d.png",
                            "-vf", f"scale={W}:{H}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                            str(out / "stage.mp4")], check=True)
    finally:
        ab("close")
    return write_events(out, "animation", seconds, spec.get("step", []))
