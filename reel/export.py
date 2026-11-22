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


def export(out: Path, spec: dict | None) -> Path:
    out = Path(out)
    master = out / "master.mp4"
    dst = out / "out"
    dst.mkdir(exist_ok=True)
    gif_cap = int(float((spec or {}).get("gif_max_mb", 10)) * MB)
    _ff("-i", str(master), "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-movflags", "+faststart", "-an", str(dst / "x.mp4"))
    _ff("-i", str(master), "-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
        "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(dst / "readme.mp4"))
    tries = gif(master, dst / "readme.gif", gif_cap)
    (dst / "export.json").write_text(json.dumps({"gif_cap_bytes": gif_cap, "gif_tries": tries}, indent=2) + "\n")
    print(f"exported {dst}: " + ", ".join(f"{p.name} {p.stat().st_size / MB:.1f} MB"
                                          for p in sorted(dst.glob('*.*')) if p.suffix != '.json'))
    return dst
