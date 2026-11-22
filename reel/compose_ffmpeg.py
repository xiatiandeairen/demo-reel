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
MOTION_BLUR_FRAMES = 3
LOOP_FADE = 0.4
FADE_OUT = 0.8
LOOP_HOLD = 0.1
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


def _window(tl: dict, start: float, end: float, with_cards: bool = False) -> dict:
    """The timeline cut down to stage seconds start..end (a clip drops the title cards)."""
    tl = dict(tl)
    tl["keep"] = [[max(a, start), min(b, end)] for a, b in tl["keep"] if min(b, end) - max(a, start) > 0.05]
    tl["captions"] = [dict(c, start=max(c["start"], start), end=min(c["end"], end))
                      for c in tl.get("captions", []) if c["end"] > start and c["start"] < end]
    if not with_cards:
        tl.pop("intro", None)
        tl.pop("outro", None)
    return tl


def compose(tl_path: Path, out_path: Path, window: tuple | None = None, loop: bool = False,
            with_cards: bool = False, fade_out: bool = True) -> Path:
    """Renders the timeline (or only stage seconds `window`) to out_path.

    fade_out: end on a fade to black (off for a scene, which the film joins with a crossfade).

    loop: the last LOOP_FADE seconds fade into the first frame, so the clip repeats without a jump.
    """
    tl = timeline.load(tl_path)
    if window:
        tl = _window(tl, *window, with_cards=with_cards)
    base = Path(tl_path).parent
    st, o = tl["stage"], tl["output"]
    fps, ow, oh = o["fps"], o["width"], o["height"]
    shots = tl["shots"]
    body = timeline.kept_seconds(tl["keep"])
    keep_expr = "+".join(f"between(t,{a},{b})" for a, b in tl["keep"])
    # Motion blur only while the camera moves (Framer-style): blend a few frames, sharp when settled.
    moves = []
    for s0, s1 in zip(shots, shots[1:]):
        if (s0["x"], s0["y"], s0["zoom"]) == (s1["x"], s1["y"], s1["zoom"]):
            continue
        a, b = timeline.output_time(tl["keep"], s0["t"]), timeline.output_time(tl["keep"], s1["t"])
        if a is not None and b is not None and b > a:
            moves.append((a, b))
    # tmix must see every frame (with a timeline switch it mixes in empty, green frames), so the
    # blurred copy runs all the time and an overlay shows it only while the camera moves.
    weights = "1 2 1"  # centre-weighted: a hint of motion, not a ghosted double image
    moving = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in moves)

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
        if moves and tl.get("style", {}).get("motion_blur"):
            g[0] = g[0].replace("[b0]", "[sharp]")
            g.append("[sharp]split[s_keep][s_blur]")
            g.append(f"[s_blur]tmix=frames={MOTION_BLUR_FRAMES}:weights='{weights}':scale=0.25[blurred]")
            g.append(f"[s_keep][blurred]overlay=0:0:enable='{moving}',format=yuv420p[b0]")
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
            cards.caption(png, c["text"], c.get("keys"), ow, oh)
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

        if not loop and fade_out:
            # The main film fades out on the whole stage instead of stopping dead (review: "ends abruptly").
            total = body + sum(tl[k]["seconds"] - XFADE for k in ("intro", "outro") if tl.get(k))
            g.append(f"[{last}]fade=t=out:st={max(0.0, total - FADE_OUT):.3f}:d={FADE_OUT}[faded]")
            last = "faded"
        if loop:
            total = body
            g.append(f"[{last}]split[lp_a][lp_b]")
            # The fade lands on the first frame and holds it a moment, so the last frame is the first.
            g.append(f"[lp_b]trim=end_frame=1,loop=loop=-1:size=1,trim=duration={LOOP_FADE + LOOP_HOLD},"
                     f"setpts=N/{fps}/TB[lp_h]")
            g.append(f"[lp_a][lp_h]xfade=transition=fade:duration={LOOP_FADE}:offset={total - LOOP_FADE:.3f}[looped]")
            last = "looped"
        script = tmp / "graph.txt"
        script.write_text(";\n".join(g))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-/filter_complex", str(script),
                        "-map", f"[{last}]", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)], check=True)
    return Path(out_path)


def fade_end(video: Path, out_path: Path) -> Path:
    """The video with its last FADE_OUT seconds fading to black."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    end = float(r.stdout.strip())
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    f"fade=t=out:st={max(0.0, end - FADE_OUT):.3f}:d={FADE_OUT}", "-c:v", "libx264", "-crf", "18",
                    "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)], check=True)
    return Path(out_path)


TARGET_LUFS = -16.0


def clip_gain(wav: Path) -> float:
    """dB that brings one sentence to TARGET_LUFS. Normalising each sentence before mixing keeps sparse
    narration at the target; one loudnorm over the whole mix fell to -24 LUFS on a scene with two
    short sentences (2026-11-22)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    import re
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    lufs = float(m[-1]) if m else TARGET_LUFS
    return round(TARGET_LUFS - lufs, 2) if lufs > -70 else 0.0


def add_narration(video: Path, items: list, out_path: Path) -> Path:
    """Mixes narration clips [(wav, seconds into the video)] under the video: each sentence at -16 LUFS,
    the loudness most social platforms normalise to (CASE-B7.2), peaks limited to about -1.5 dBTP."""
    inputs, chains = ["-i", str(video)], []
    for i, (wav, at) in enumerate(items, 1):
        inputs += ["-i", str(wav)]
        ms = int(at * 1000)
        chains.append(f"[{i}:a]aresample=48000,volume={clip_gain(Path(wav))}dB,adelay={ms}|{ms}[n{i}]")
    mix = "".join(f"[n{i}]" for i in range(1, len(items) + 1))
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    end = float(r.stdout.strip())
    graph = (";".join(chains) + f";{mix}amix=inputs={len(items)}:normalize=0,apad,alimiter=limit=0.84:level=false,"
             f"afade=t=out:st={max(0.0, end - FADE_OUT):.3f}:d={FADE_OUT}[a]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-map", "0:v",
                    "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
                    "-movflags", "+faststart", str(out_path)], check=True)
    return Path(out_path)
