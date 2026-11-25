"""Renders a timeline with ffmpeg alone: camera moves, cuts, captions, timer bars.

Captions and timer labels are PNGs drawn by headless Chrome (cards.py), because this ffmpeg build may
lack drawtext. The camera is a zoompan over the stage scaled up 2x, so sub-pixel moves stay smooth.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from . import cards, timeline

XFADE = 0.4
FADE_OUT = 0.8
OUTPUT = {"width": 1920, "height": 1080, "fps": 30}
CAPTION_FADE = 0.25


# Timer bars (CASE-D1.2): rows in a dark panel above the captions, as shares of the output frame.
TIMER_X0, TIMER_X1 = 0.18, 0.82
TIMER_ROW_H = 0.062
TIMER_BOTTOM = 0.17          # the panel's bottom edge, above the caption
TIMER_LABEL_W, TIMER_VALUE_W = 0.13, 0.09
TIMER_COLOURS = ["0xe0a030", "0x1596b8", "0x8f6bff"]


def timer_width(t: float, start: float, seconds: float, scale: float, track: int) -> int:
    """Pixels of a timer bar at film time t: grows with real time, stops at seconds / scale of the track."""
    return int(track * min(min(1.0, seconds / scale), max(0.0, t - start) / scale))


def _timer_geometry(ow: int, oh: int, rows: int) -> dict:
    x0, x1 = int(ow * TIMER_X0), int(ow * TIMER_X1)
    row_h = int(oh * TIMER_ROW_H)
    y1 = int(oh * (1 - TIMER_BOTTOM))
    y0 = y1 - rows * row_h
    track_x = x0 + int(ow * TIMER_LABEL_W)
    track_w = x1 - int(ow * TIMER_VALUE_W) - track_x
    return {"x0": x0, "x1": x1, "y0": y0, "row_h": row_h, "track_x": track_x, "track_w": track_w,
            "bar_h": int(row_h * 0.42)}


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


def compose(tl_path: Path, out_path: Path, fade_out: bool = True) -> Path:
    """Renders a scene's timeline to out_path at OUTPUT size and frame rate.

    fade_out: end on a fade to black (off for a scene, which a cut joins with a crossfade).
    """
    tl = timeline.load(tl_path)
    base = Path(tl_path).parent
    st = tl["stage"]
    fps, ow, oh = OUTPUT["fps"], OUTPUT["width"], OUTPUT["height"]
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
            cards.caption(png, c["text"], c.get("keys"), ow, oh)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{body:.3f}", "-i", str(png)]
            g.append(f"[{n}:v]format=rgba,fade=t=in:st={s:.3f}:d={CAPTION_FADE}:alpha=1,"
                     f"fade=t=out:st={e - CAPTION_FADE:.3f}:d={CAPTION_FADE}:alpha=1[c{i}]")
            g.append(f"[{last}][c{i}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})',format=yuv420p[o{i}]")
            last, n = f"o{i}", n + 1

        timers = tl.get("timers", [])
        if timers:
            geo = _timer_geometry(ow, oh, len(timers))
            panel = tmp / "timers.png"
            cards.timer_panel(panel, [tm["label"] for tm in timers], geo, ow, oh)
            starts = [timeline.output_time(tl["keep"], tm["start"]) for tm in timers]
            shown = min((st for st in starts if st is not None), default=0.0)
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{body:.3f}", "-i", str(panel)]
            g.append(f"[{n}:v]format=rgba,fade=t=in:st={shown:.3f}:d=0.3:alpha=1[tp]")
            g.append(f"[{last}][tp]overlay=0:0:enable='gte(t,{shown:.3f})',format=yuv420p[tpo]")
            last, n = "tpo", n + 1
            for k, (tm, st) in enumerate(zip(timers, starts)):
                if st is None:
                    continue
                cap = min(1.0, tm["seconds"] / tm["scale"])
                y = geo["y0"] + k * geo["row_h"] + (geo["row_h"] - geo["bar_h"]) // 2
                colour = TIMER_COLOURS[k % len(TIMER_COLOURS)]
                inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s={geo['track_w']}x{geo['bar_h']}:d={body:.3f}:r={fps}"]
                g.append(f"[{n}:v]scale=w='max(2,{geo['track_w']}*min({cap:.4f},max(0,t-{st:.3f})/{tm['scale']}))'"
                         f":h={geo['bar_h']}:eval=frame[tf{k}]")
                g.append(f"[{last}][tf{k}]overlay={geo['track_x']}:{y}:eval=frame:enable='gte(t,{st:.3f})',format=yuv420p[tb{k}]")
                last, n = f"tb{k}", n + 1
                done = st + tm["seconds"]
                val = tmp / f"timer{k}.png"
                cards.timer_value(val, f"{tm['seconds']:.1f} s", geo, k, ow, oh)
                inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{body:.3f}", "-i", str(val)]
                g.append(f"[{n}:v]format=rgba,fade=t=in:st={done:.3f}:d=0.25:alpha=1[tv{k}]")
                g.append(f"[{last}][tv{k}]overlay=0:0:enable='gte(t,{done:.3f})',format=yuv420p[tvo{k}]")
                last, n = f"tvo{k}", n + 1

        if fade_out:
            g.append(f"[{last}]fade=t=out:st={max(0.0, body - FADE_OUT):.3f}:d={FADE_OUT}[faded]")
            last = "faded"
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
