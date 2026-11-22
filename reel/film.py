"""A film: scenes recorded on their own, joined with crossfades, narrated and checked as one.

Each scene is an ordinary spec with its own state directory. Composing a scene leaves
scene.mp4 (silent, no fade-out) and narration.json there; the film only reads those, so
`reel compose film.toml` re-joins without recording again. Card scenes are drawn again on
every compose, because their numbers come from what the other scenes logged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import paths, spec as spec_mod
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


def make_all(scenes: list, make) -> None:
    """Makes the scenes in order; a failure names its scene and leaves finished scenes as they are (CASE-C8)."""
    for p in scenes:
        try:
            make(p)
        except Exception as e:  # noqa: BLE001 - reported with the scene's name, then stops the film
            raise FilmError(f"scene {Path(p).name}: {e}") from e


def _duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def stitch(film: dict, out: Path, make_scene) -> bool:
    """out/master.mp4 from the scenes' scene.mp4; returns whether any scene is narrated."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    videos, durations, per_scene = [], [], []
    for p in film["_scenes"]:
        sc = spec_mod.load(p)
        st = paths.state_dir(sc)
        if sc["kind"] == "card":
            make_scene(sc, st)  # numbers come from the latest recordings
        video = st / "scene.mp4"
        if not video.exists():
            raise FilmError(f"scene {Path(p).name} has not been recorded: reel make {p}")
        videos.append(video)
        durations.append(_duration(video))
        narr = st / "narration.json"
        per_scene.append([(str(st / n["wav"]), n["at"]) for n in json.loads(narr.read_text())] if narr.exists() else [])
    starts, total = scene_starts(durations)
    items = shift_items(per_scene, starts)

    inputs = [a for v in videos for a in ("-i", str(v))]
    g, last = [], "0:v"
    for k in range(1, len(videos)):
        g.append(f"[{last}][{k}:v]xfade=transition=fade:duration={XFADE}:offset={starts[k]:.3f}[x{k}]")
        last = f"x{k}"
    g.append(f"[{last}]fade=t=out:st={max(0.0, total - FADE_OUT):.3f}:d={FADE_OUT},format=yuv420p[v]")
    silent = out / "master-silent.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(g), "-map", "[v]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(silent)], check=True)
    master = out / "master.mp4"
    if items:
        add_narration(silent, items, master)
    else:
        shutil.copy(silent, master)
    (out / "film.json").write_text(json.dumps(
        {"scenes": [{"spec": p, "start": s, "seconds": round(d, 3)} for p, s, d in zip(film["_scenes"], starts, durations)],
         "seconds": total, "narrated": bool(items)}, indent=2) + "\n")
    print(f"composed {master} ({len(videos)} scenes, {total:.1f} s)")
    return bool(items)
