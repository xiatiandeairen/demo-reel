"""Checks the deliverables before anyone sees them: only what an AI reviewing the contact sheets cannot
see (docs/problem-model.md, goal 5): file sizes, format and length, sensitive text, narration loudness,
and that each deliverable comes from its latest cut.

Sensitive text is found by OCR (macOS Vision, tools/ocr.swift) on frames every half second.
Your own extra patterns (company domains, internal hosts) go in
~/.config/demo-reel/private.txt, one regular expression per line, so they stay out of any repo.
"""
from __future__ import annotations

import getpass
import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import paths

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


def patterns(spec: dict | None = None) -> list:
    pats = list(SECRETS)
    user = getpass.getuser()
    if len(user) >= 3:
        pats.append(("user name", rf"\b{re.escape(user)}\b"))
    private = paths.config_root() / "private.txt"
    if private.exists():
        for line in private.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                pats.append(("private pattern", line.strip()))
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
    cache = paths.cache_root()
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
                        "stream=codec_name,profile,pix_fmt,width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return {**s, "duration": float(d["format"]["duration"])}


def loudness(path: Path) -> float | None:
    """Integrated loudness in LUFS, or None without an audio track (CASE-B7.2)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m and "Audio" in r.stderr else None


LIMITS = {"share": 90, "readme": 90, "gif": 30}   # seconds (docs/problem-model.md, 交付物)


def sensitive(videos: list, pats: list, leaks_dir: Path) -> list:
    """OCR hits in every video, each with a screenshot in leaks_dir."""
    leaks = []
    for video in videos:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps=1/{OCR_EVERY}",
                            f"{tmp}/f%04d.png"], check=True)
            for path, lines in ocr(sorted(Path(tmp).glob("f*.png"))).items():
                hits = find_sensitive(lines, pats)
                if hits:
                    t = (int(Path(path).stem[1:]) - 1) * OCR_EVERY
                    shot = leaks_dir / f"{Path(video).stem}-{t:05.1f}.png"
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    Path(path).replace(shot)
                    leaks.append({"video": Path(video).name, "t": t, "hits": hits, "screenshot": str(shot)})
    return leaks


def check(made: dict, gif_cut: Path, stamps: dict, narrated: bool, leaks_dir: Path) -> list:
    """[{name, ok, detail}] for the deliverables `made` (export's result). gif_cut: the GIF's cut video,
    read for sensitive text; stamps: {cut: its current stamp}, each deliverable's made-from stamp is in made."""
    results = []

    def add(name, ok, detail):
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    share, readme, gif = (Path(made[k]["path"]) for k in ("share.mp4", "readme.mp4", "gif"))
    s, r = probe(share), probe(readme)
    sizes = {"readme.mp4": readme.stat().st_size, "GIF": gif.stat().st_size}
    tries = ", ".join(f"{t['width']}px/{t['fps']}fps={t['bytes'] / MB:.1f}MB" for t in made["gif"]["tries"])
    add("size", all(v <= 10 * MB for v in sizes.values()),
        " · ".join(f"{k} {v / MB:.1f} / 10 MB" for k, v in sizes.items()) + (f" (tried {tries})" if len(made["gif"]["tries"]) > 1 else ""))
    g = probe(gif)
    fmt_ok = (s["codec_name"] == "h264" and s.get("profile") == "High" and s["pix_fmt"] == "yuv420p"
              and (s["width"], s["height"]) == (1920, 1080) and r["codec_name"] == "h264")
    long = [f"{n} {d:.1f} / {LIMITS[c]} s" for n, c, d in (("share.mp4", "share", s["duration"]),
            ("readme.mp4", "readme", r["duration"]), ("GIF", "gif", g["duration"]))]
    add("format", fmt_ok and s["duration"] <= LIMITS["share"] + 0.05 and r["duration"] <= LIMITS["readme"] + 0.05
        and g["duration"] <= LIMITS["gif"] + 0.05,
        f"share.mp4 {s['codec_name']} {s.get('profile')} {s['width']}x{s['height']} · " + " · ".join(long))
    pats = patterns(None)
    leaks = sensitive([share, readme, gif_cut], pats, leaks_dir)
    add("sensitive", not leaks, "none found" if not leaks else
        "; ".join(f"{l['video']} at {l['t']:.1f} s: {h[0]} {h[1]!r} ({l['screenshot']})" for l in leaks for h in l["hits"]))
    if narrated:
        lufs = {n: loudness(v) for n, v in (("share.mp4", share), ("readme.mp4", readme))}
        add("loudness", all(v is not None and abs(v + 16) <= 2 for v in lufs.values()),
            " · ".join(f"{n} {'no audio' if v is None else f'{v:.1f} LUFS'}" for n, v in lufs.items()) + " (target -16 ± 2)")
    stale = [n for n, m in made.items() if stamps.get(m["cut"]) != m.get("cut_stamp")]
    add("fresh", not stale, "each deliverable is from its latest cut" if not stale else
        f"{', '.join(stale)} not made from the latest cut: run reel make again")
    return results


def print_report(results: list):
    print("CHECKS")
    for r in results:
        print(f"  {'ok  ' if r['ok'] else 'FAIL'}  {r['name']:<10}{r['detail']}")
