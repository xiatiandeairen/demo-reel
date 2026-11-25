"""Platform files from the cuts (docs/design.md).

    share.mp4   X and YouTube: 1920x1080 H.264 High, yuv420p, faststart (X plays it muted, autoplay)
    readme.mp4  the README video: 1280x720 H.264, under GitHub's 10 MB
    <name>.gif  the README GIF: tried at falling quality until it fits 10 MB; written into the project's
                assets/ only after the checks pass (cli.py)

Limits (checked 2026-11-21): GitHub images, GIFs and videos on free plans 10 MB
(docs.github.com/.../attaching-files); YouTube's recommended upload settings: MP4, H.264 High Profile, 4:2:0
(support.google.com/youtube/answer/1722171).
"""
from __future__ import annotations

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
GIF_CAP = 10 * MB


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


def export(cuts: dict, dst: Path) -> dict:
    """share.mp4 and readme.mp4 in dst, and the GIF as dst/pending.gif; cuts: {cut: its master.mp4}.
    Returns {deliverable: {"path", "cut", "tries"?}}."""
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    _video(cuts["share"], dst / "share.mp4", None, 20)
    _video(cuts["readme"], dst / "readme.mp4", 1280, 26)
    tries = gif(cuts["gif"], dst / "pending.gif", GIF_CAP)
    return {"share.mp4": {"path": str(dst / "share.mp4"), "cut": "share"},
            "readme.mp4": {"path": str(dst / "readme.mp4"), "cut": "readme"},
            "gif": {"path": str(dst / "pending.gif"), "cut": "gif", "tries": tries}}
