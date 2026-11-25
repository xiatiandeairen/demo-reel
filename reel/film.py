"""Cuts: the scenes of one deliverable joined with crossfades, narrated as one (docs/design.md).

Each scene's edit leaves scene.mp4 (silent, no fade-out) and the narration's place in it (timeline.json);
a cut only reads those, so changing a scene's order or a card needs no new take.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .compose_ffmpeg import FADE_OUT, XFADE, add_narration


class FilmError(RuntimeError):
    pass


def scene_starts(durations: list, xfade: float = XFADE) -> tuple:
    """Where each scene starts in the film, and the film's length: neighbours overlap by one crossfade (CASE-C6.2)."""
    starts, t = [], 0.0
    for d in durations:
        starts.append(round(t, 3))
        t += d - xfade
    return starts, round(t + xfade, 3) if durations else 0.0


def shift_items(per_scene: list, starts: list) -> list:
    """Narration [(wav, seconds)] of every scene, moved to film time (CASE-C6.2)."""
    return [(wav, round(s + at, 3)) for items, s in zip(per_scene, starts) for wav, at in items]


def _duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def stitch(scenes: list, out: Path, fade_out: bool = True) -> dict:
    """out/master.mp4 and out/cut.json from scenes [(id, scene.mp4, [(wav, seconds)], head)], in order;
    head: seconds cut from the scene's start (a terminal scene later in a cut opens on its layout for
    0.6 s instead of 1.5 s: the crossfade already showed it)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    durations = [_duration(v) - head for _, v, _, head in scenes]
    starts, total = scene_starts(durations)
    items = shift_items([[(w, round(at - head, 3)) for w, at in n if at - head >= 0] for _, _, n, head in scenes], starts)
    inputs = [a for _, v, _, _ in scenes for a in ("-i", str(v))]
    g = [f"[{k}:v]trim=start={head:.3f},setpts=PTS-STARTPTS[s{k}]" for k, (_, _, _, head) in enumerate(scenes)]
    last = "s0"
    for k in range(1, len(scenes)):
        g.append(f"[{last}][s{k}]xfade=transition=fade:duration={XFADE}:offset={starts[k]:.3f}[x{k}]")
        last = f"x{k}"
    tail = f"fade=t=out:st={max(0.0, total - FADE_OUT):.3f}:d={FADE_OUT}," if fade_out else ""
    g.append(f"[{last}]{tail}format=yuv420p[v]")
    silent = out / "master-silent.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(g), "-map", "[v]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(silent)], check=True)
    master = out / "master.mp4"
    if items:
        add_narration(silent, items, master)
        silent.unlink()
    else:
        shutil.move(str(silent), master)
    cut = {"scenes": [{"id": sid, "start": s, "seconds": round(d, 3)} for (sid, _, _, _), s, d in zip(scenes, starts, durations)],
           "seconds": total, "narrated": bool(items)}
    (out / "cut.json").write_text(json.dumps(cut, indent=2) + "\n")
    return cut
