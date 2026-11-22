"""Checks exported files before anyone sees them: platform limits, first frame, sensitive text.

Sensitive text is found by OCR (macOS Vision, tools/ocr.swift) on frames every half second.
Your own extra patterns (company domains, internal hosts) go in
~/.config/demo-reel/private.txt, one regular expression per line, so they stay out of any repo.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

MB = 1024 * 1024
OCR_EVERY = 0.5
SECRETS = [
    ("GitHub token", r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    ("API key", r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("AWS key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitLab token", r"\bglpat-[A-Za-z0-9_-]{20,}"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"),
    ("home path", r"/(Users|home)/(?!Shared\b)[A-Za-z0-9._-]+"),
]


def patterns(spec: dict | None) -> list:
    pats = list(SECRETS)
    user = getpass.getuser()
    if len(user) >= 3:
        pats.append(("user name", rf"\b{re.escape(user)}\b"))
    private = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "demo-reel" / "private.txt"
    if private.exists():
        for line in private.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                pats.append(("private pattern", line.strip()))
    for p in (spec or {}).get("private", []):
        pats.append(("private pattern", p))
    return [(name, re.compile(rx, re.I if name != "API key" else 0)) for name, rx in pats]


def find_sensitive(lines: list, pats: list) -> list:
    """[(kind, matched text)] for OCR lines (CASE-A4.1)."""
    hits = []
    for line in lines:
        for name, rx in pats:
            m = rx.search(line)
            if m:
                hits.append((name, m.group(0)))
    return hits


def _ocr_bin() -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "demo-reel"
    exe = cache / "ocr"
    src = Path(__file__).resolve().parent.parent / "tools" / "ocr.swift"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", "-o", str(exe), str(src)], check=True, capture_output=True)
    return exe


def ocr(images: list) -> dict:
    r = subprocess.run([str(_ocr_bin()), *map(str, images)], capture_output=True, text=True, check=True)
    return {d["path"]: d["lines"] for d in map(json.loads, r.stdout.splitlines())}


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,pix_fmt,width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return {**s, "duration": float(d["format"]["duration"])}


def _first_frame_spread(path: Path) -> float:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-frames:v", "1", "-vf",
                          "scale=96:54,format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    mean = sum(raw) / len(raw)
    return (sum((v - mean) ** 2 for v in raw) / len(raw)) ** 0.5


CLIP_SECONDS = (4, 15)
LOOP_GAP_MAX = 6.0  # mean gray-level difference (0-255) between a clip's first and last frame


def _gray(path: Path, where: list) -> bytes:
    return subprocess.run(["ffmpeg", "-loglevel", "error", *where, "-i", str(path), "-frames:v", "1", "-vf",
                           "scale=96:54,format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout


def loop_gap(path: Path) -> float:
    """How far a clip's last frame is from its first (CASE-B6.1): near 0 means it loops cleanly."""
    a, b = _gray(path, []), _gray(path, ["-sseof", "-0.05"])
    return sum(abs(x - y) for x, y in zip(a, b)) / max(len(a), 1)


def loudness(path: Path) -> float | None:
    """Integrated loudness in LUFS, or None without an audio track (CASE-B7.2)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m and "Audio" in r.stderr else None


def check(out: Path, spec: dict | None) -> dict:
    out = Path(out)
    d = out / "out"
    spec = spec or {}
    max_s = float(spec.get("max_seconds", 30))
    gif_cap = float(spec.get("gif_max_mb", 10)) * MB
    results = []

    def add(name, ok, detail):
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    x = probe(d / "x.mp4")
    add("x.mp4 format", x["codec_name"] == "h264" and x["pix_fmt"] == "yuv420p"
        and (x["width"], x["height"]) == (1920, 1080), f"{x['codec_name']} {x['pix_fmt']} {x['width']}x{x['height']}")
    add("length", x["duration"] <= max_s + 0.05, f"{x['duration']:.1f} s (limit {max_s:.0f} s)")
    rm = probe(d / "readme.mp4")
    rm_size = (d / "readme.mp4").stat().st_size
    add("readme.mp4", rm["codec_name"] == "h264" and rm["pix_fmt"] == "yuv420p" and rm_size <= 10 * MB,
        f"{rm['width']}x{rm['height']} {rm_size / MB:.1f} MB (limit 10 MB)")
    all_tries = json.loads((d / "export.json").read_text())["gif_tries"]
    for name, tries in all_tries.items():
        g = (d / name).stat().st_size
        add(f"{name} size", g <= gif_cap, f"{g / MB:.1f} MB (limit {gif_cap / MB:.0f} MB); tried "
            + ", ".join(f"{t['width']}px/{t['fps']}fps/{t['colors']}c={t['bytes'] / MB:.1f}MB" for t in tries))
    for clip in sorted((d / "clips").glob("*.mp4")) if (d / "clips").exists() else []:
        c = probe(clip)
        add(f"clips/{clip.name} length", CLIP_SECONDS[0] <= c["duration"] <= CLIP_SECONDS[1],
            f"{c['duration']:.1f} s (want {CLIP_SECONDS[0]}-{CLIP_SECONDS[1]} s)")
        diff = loop_gap(clip)
        add(f"clips/{clip.name} loops", diff <= LOOP_GAP_MAX, f"first vs last frame differ by {diff:.1f} (limit {LOOP_GAP_MAX})")
    if spec.get("voice"):
        lufs = loudness(d / "x.mp4")
        add("narration loudness", lufs is not None and abs(lufs + 16) <= 2,
            "no audio track" if lufs is None else f"{lufs:.1f} LUFS (target -16 ± 2)")
    spread = _first_frame_spread(d / "x.mp4")
    add("first frame", spread > 8, f"contrast {spread:.0f} (a blank frame is near 0)")

    pats = patterns(spec)
    leaks = []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(d / "x.mp4"), "-vf", f"fps=1/{OCR_EVERY}",
                        f"{tmp}/f%04d.png"], check=True)
        frames = sorted(Path(tmp).glob("f*.png"))
        for path, lines in ocr(frames).items():
            hits = find_sensitive(lines, pats)
            if hits:
                t = (int(Path(path).stem[1:]) - 1) * OCR_EVERY
                shot = d / "leaks" / f"t{t:05.1f}.png"
                shot.parent.mkdir(exist_ok=True)
                Path(path).replace(shot)
                leaks.append({"t": t, "hits": hits, "screenshot": str(shot)})
    add("sensitive text", not leaks,
        "none found" if not leaks else "; ".join(f"{l['t']:.1f}s {h[0]} {h[1]!r}" for l in leaks for h in l["hits"]))
    report = {"ok": all(r["ok"] for r in results), "dir": str(d), "checks": results, "leaks": leaks}
    (d / "check.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def print_report(report: dict):
    print(f"check: {'PASS' if report['ok'] else 'FAIL'}  ({report['dir']})")
    for r in report["checks"]:
        print(f"  {'ok ' if r['ok'] else 'BAD'} {r['name']}: {r['detail']}")
