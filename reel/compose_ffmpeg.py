"""Renders a timeline with ffmpeg alone: camera moves, cuts, captions, title cards.

Captions and cards are PNGs drawn by headless Chrome (cards.py), because this ffmpeg build may
lack drawtext. The camera is a zoompan over the stage scaled up 2x, so sub-pixel moves stay smooth.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from . import cards, timeline

XFADE = 0.4
CAPTION_FADE = 0.25


def _ease(a, b, t0, t1, log=False):
    s = f"(((T-{t0})/{t1 - t0}))"
    s = f"({s}*{s}*(3-2*{s}))"
    if log:
        return f"exp({math.log(a)}+({math.log(b) - math.log(a)})*{s})"
    return f"({a}+({b - a})*{s})"


def _track(shots, key, fps, log=False):
    expr = str(shots[-1][key])
    for s0, s1 in reversed(list(zip(shots, shots[1:]))):
        if s1["t"] <= s0["t"]:
            continue
        seg = str(s0[key]) if s0[key] == s1[key] else _ease(s0[key], s1[key], s0["t"], s1["t"], log)
        expr = f"if(lt(T,{s1['t']}),{seg},{expr})"
    expr = f"if(lt(T,{shots[0]['t']}),{shots[0][key]},{expr})"
    return expr.replace("T", f"(in/{fps})")


def compose(tl_path: Path, out_path: Path) -> Path:
    tl = timeline.load(tl_path)
    base = Path(tl_path).parent
    st, o = tl["stage"], tl["output"]
    fps, ow, oh = o["fps"], o["width"], o["height"]
    shots = tl["shots"]
    body = timeline.kept_seconds(tl["keep"])
    keep_expr = "+".join(f"between(t,{a},{b})" for a, b in tl["keep"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        inputs = ["-i", str(base / st["path"])]
        g = [
            f"[0:v]fps={fps},scale=iw*2:ih*2:flags=lanczos,"
            f"zoompan=z='{_track(shots, 'zoom', fps, log=True)}'"
            f":x='clip(2*{_track(shots, 'x', fps)}-iw/zoom/2,0,iw-iw/zoom)'"
            f":y='clip(2*{_track(shots, 'y', fps)}-ih/zoom/2,0,ih-ih/zoom)'"
            f":d=1:fps={fps}:s={ow}x{oh},"
            f"select='{keep_expr}',setpts=N/{fps}/TB,format=yuv420p,setsar=1[b0]"
        ]
        last = "b0"
        n = 1
        for i, c in enumerate(tl.get("captions", [])):
            s = timeline.output_time(tl["keep"], c["start"])
            e = timeline.output_time(tl["keep"], c["end"])
            s = 0.0 if s is None else s
            e = body if e is None else e
            if e - s < 0.6:
                continue
            png = tmp / f"cap{i}.png"
            cards.caption(png, c["text"], ow, oh)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{body:.3f}", "-i", str(png)]
            g.append(f"[{n}:v]format=rgba,fade=t=in:st={s:.3f}:d={CAPTION_FADE}:alpha=1,"
                     f"fade=t=out:st={e - CAPTION_FADE:.3f}:d={CAPTION_FADE}:alpha=1[c{i}]")
            g.append(f"[{last}][c{i}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})',format=yuv420p[o{i}]")
            last, n = f"o{i}", n + 1

        offset = 0.0
        if tl.get("intro"):
            it = tl["intro"]
            png = tmp / "intro.png"
            cards.title_card(png, it["title"], it.get("subtitle", ""), tl["style"]["accent"], ow, oh)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{it['seconds']:.3f}", "-i", str(png)]
            g.append(f"[{n}:v]format=yuv420p,setsar=1[intro]")
            g.append(f"[intro][{last}]xfade=transition=fade:duration={XFADE}:offset={it['seconds'] - XFADE:.3f}[withintro]")
            last, n = "withintro", n + 1
            offset = it["seconds"] - XFADE
        if tl.get("outro"):
            ot = tl["outro"]
            png = tmp / "outro.png"
            cards.title_card(png, ot["title"], ot.get("subtitle", ""), tl["style"]["accent"], ow, oh)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{ot['seconds']:.3f}", "-i", str(png)]
            g.append(f"[{n}:v]format=yuv420p,setsar=1[outro]")
            g.append(f"[{last}][outro]xfade=transition=fade:duration={XFADE}:offset={offset + body - XFADE:.3f}[withoutro]")
            last, n = "withoutro", n + 1

        script = tmp / "graph.txt"
        script.write_text(";\n".join(g))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-/filter_complex", str(script),
                        "-map", f"[{last}]", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)], check=True)
    return Path(out_path)
