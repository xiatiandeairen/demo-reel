"""Platform files from a master video.

    x.mp4       X timeline: 1920x1080 H.264, yuv420p, faststart (plays muted, autoplay)
    readme.mp4  GitHub README video: 1280x720 H.264, under the GIF/video cap
    readme.gif  GitHub README GIF: tried at falling quality until it fits the cap

Limits (checked 2026-11-21): GitHub images, GIFs and videos on free plans 10 MB
(docs.github.com/.../attaching-files); X GIF 15 MB (docs.x.com/x-api/media/quickstart/best-practices).
A spec can lower `gif_max_mb` (for example 5 for a plugin directory that is stricter).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import paths

GIF_LADDER = [  # (width, fps, colors)
    (1120, 15, 128),
    (960, 12, 128),
    (880, 12, 96),
    (800, 10, 96),
    (720, 10, 64),
]
MB = 1024 * 1024


def _ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def gif(src: Path, dst: Path, max_bytes: int) -> list:
    """Writes the best GIF that fits; returns every attempt [(width, fps, colors, bytes)] (CASE-A4.2)."""
    tries = []
    for w, fps, colors in GIF_LADDER:
        _ff("-i", str(src), "-filter_complex",
            f"fps={fps},scale={w}:-2:flags=lanczos,split[a][b];"
            f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
            f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", str(dst))
        size = dst.stat().st_size
        tries.append({"width": w, "fps": fps, "colors": colors, "bytes": size})
        if size <= max_bytes:
            break
    return tries


def _has_audio(path: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _video(src: Path, dst: Path, width: int | None, crf: int):
    audio = ["-c:a", "aac", "-b:a", "160k"] if _has_audio(src) else ["-an"]
    scale = ["-vf", f"scale={width}:-2:flags=lanczos"] if width else []
    _ff("-i", str(src), *scale, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-movflags", "+faststart", *audio, str(dst))


def export(out: Path, spec: dict | None) -> Path:
    """out/x.mp4, readme.mp4, readme.gif for the main film; out/clips/<name>.mp4 and .gif for
    each feature clip. Narration, if any, stays on the mp4s; GIFs are silent by nature."""
    out = Path(out)
    master = out / "master.mp4"
    dst = paths.deliverables(out)
    dst.mkdir(parents=True, exist_ok=True)
    gif_cap = int(float((spec or {}).get("gif_max_mb", 10)) * MB)
    _video(master, dst / "x.mp4", None, 20)
    _video(master, dst / "readme.mp4", 1280, 26)
    tries = {"readme.gif": gif(master, dst / "readme.gif", gif_cap)}
    clips_src = sorted((out / "clips").glob("*.mp4")) if (out / "clips").exists() else []
    if clips_src:
        (dst / "clips").mkdir(exist_ok=True)
    for src in clips_src:
        _video(src, dst / "clips" / src.name, 1280, 24)
        tries[f"clips/{src.stem}.gif"] = gif(src, dst / "clips" / f"{src.stem}.gif", gif_cap)
    (dst / "export.json").write_text(json.dumps({"gif_cap_bytes": gif_cap, "gif_tries": tries}, indent=2) + "\n")
    files = sorted(p for p in dst.rglob("*") if p.suffix in (".mp4", ".gif"))
    print(f"exported {dst}: " + ", ".join(f"{p.relative_to(dst)} {p.stat().st_size / MB:.1f} MB" for p in files))
    return dst
