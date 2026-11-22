"""Presenter mode: you watch the finished film and talk over it; reel adds your camera and voice.

    reel narrate <dir> [--camera 0] [--mic 0]

1. Renders the film once without captions (your words become the captions).
2. Plays it full screen while recording camera and microphone (avfoundation), after a countdown.
3. Transcribes what you said with mlx-whisper (local) into timed sentences.
4. Writes out/x-presenter.mp4 and out/readme-presenter.mp4: the film, your camera in a rounded
   window bottom right, your voice at -16 LUFS, and your sentences as captions.

The terminal that runs it needs Camera and Microphone permission (macOS asks the first time).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import cards, timeline, voice
from .compose_ffmpeg import compose

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CHUNK_WORDS = 7
CHUNK_PAUSE = 0.6
PIP = 360          # camera window size on the 1920x1080 film
PIP_MARGIN = 48
COUNTDOWN = 3
FACE_ROOM = 2.2  # window height as a multiple of the face height


def _clean_master(out: Path) -> Path:
    """The main film (its [film] range, if any) without captions, from the same timeline."""
    tl = timeline.load(out / "timeline.json")
    tl["captions"] = []
    clean_tl = out / "timeline-nocaptions.json"
    timeline.save(tl, clean_tl)
    dst = out / "master-nocaptions.mp4"
    compose(clean_tl, dst, window=tuple(tl["film"]) if tl.get("film") else None, with_cards=True)
    return dst


def _mic_bin() -> Path:
    from .check import _ocr_bin  # same build-once cache as the OCR helper
    src = Path(__file__).resolve().parent.parent / "tools" / "mic.swift"
    exe = _ocr_bin().parent / "mic"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(["swiftc", "-O", "-o", str(exe), str(src)], check=True, capture_output=True)
    return exe


def _record(film: Path, cam: Path, mic_wav: Path, camera: str, mic: str) -> tuple:
    """Plays the film while recording the camera (ffmpeg) and the microphone (AVAudioEngine).

    ffmpeg's avfoundation audio clicked at every buffer boundary (every 85 ms, visible as regular
    vertical lines in a spectrogram), with or without video in the same process; the native
    recorder in tools/mic.swift did not (CASE-B8.3). `mic` is kept for the camera-only ffmpeg call's
    signature; the native recorder uses the system's default input.
    Returns (video offset, audio offset): seconds from each recording's start to playback.
    """
    caf = mic_wav.with_suffix(".caf")
    rec_a = subprocess.Popen([str(_mic_bin()), str(caf)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    if rec_a.stdout.readline().strip() != "recording":
        raise RuntimeError("microphone recording failed: does this terminal have Microphone permission?")
    t_a = time.monotonic()
    rec_v = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "avfoundation", "-thread_queue_size", "4096",
                              "-framerate", "30", "-video_size", "1280x720", "-pixel_format", "nv12",
                              "-i", f"{camera}:none", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                              str(cam)], stdin=subprocess.PIPE)
    t_v = time.monotonic()
    for n in range(COUNTDOWN, 0, -1):
        print(f"  starting in {n}…", flush=True)
        time.sleep(1)
    t_play = time.monotonic()
    subprocess.run(["ffplay", "-loglevel", "error", "-autoexit", "-fs", "-an", "-window_title", "demo-reel narrate", str(film)])
    time.sleep(0.5)
    rec_v.communicate(b"q")
    rec_a.communicate("\n")
    if not cam.exists() or not caf.exists():
        raise RuntimeError("camera or microphone recording failed: does this terminal have Camera and Microphone permission?")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(caf), "-ac", "1", "-ar", "48000",
                    "-c:a", "pcm_s16le", str(mic_wav)], check=True)
    caf.unlink()
    return t_play - t_v, t_play - t_a


def _transcribe(raw: Path, offset: float, hint: str = "") -> list:
    """[{start, end, text}] in film seconds."""
    py = voice.ensure()
    check = subprocess.run([str(py), "-c", "import mlx_whisper"], capture_output=True, env=voice._env())
    if check.returncode != 0:
        subprocess.run(["uv", "pip", "install", "-q", "--python", str(py), "mlx-whisper"], check=True)
    code = ("import json,sys,mlx_whisper;"
            f"r=mlx_whisper.transcribe(sys.argv[1],path_or_hf_repo='{WHISPER_MODEL}',initial_prompt=sys.argv[2] or None,"
            "word_timestamps=True);"
            "print(json.dumps([[w['start'],w['end'],w['word']] for s in r['segments'] for w in s.get('words',[])]))")
    r = subprocess.run([str(py), "-c", code, str(raw), hint], capture_output=True, text=True, env=voice._env(), check=True)
    words = json.loads(r.stdout.strip().splitlines()[-1])
    return [dict(c, start=round(c["start"] - offset, 3), end=round(c["end"] - offset, 3))
            for c in chunk_words(words) if c["end"] - offset > 0]


def chunk_words(words: list) -> list:
    """Timed words -> short caption lines (CASE-B8.1): at most CHUNK_WORDS words, split at a pause
    or after a sentence end, so captions follow the speaker instead of a 20-second paragraph."""
    chunks, cur = [], []
    for start, end, word in words:
        if cur and (len(cur) >= CHUNK_WORDS or start - cur[-1][1] > CHUNK_PAUSE
                    or (cur[-1][2].strip()[-1:] in ".?!" and len(cur) >= 3)):
            chunks.append(cur)
            cur = []
        cur.append((start, end, word))
    if cur:
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1][0][0] if i + 1 < len(chunks) else c[-1][1] + 0.4
        out.append({"start": c[0][0], "end": min(c[-1][1] + 0.4, nxt), "text": "".join(w for _, _, w in c).strip()})
    return out


def _face_crop(raw: Path, offset: float) -> str:
    """ffmpeg crop that keeps the speaker's face in the middle of the square window (macOS Vision),
    or a centre crop if no face is found."""
    from .check import _ocr_bin  # same build-once pattern as the OCR helper
    src = Path(__file__).resolve().parent.parent / "tools" / "face.swift"
    exe = _ocr_bin().parent / "face"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(["swiftc", "-O", "-o", str(exe), str(src)], check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as tmp:
        shots = []
        for i, t in enumerate((offset + 2, offset + 6, offset + 10)):
            png = Path(tmp) / f"f{i}.png"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(raw), "-frames:v", "1",
                            str(png)], check=True)
            if png.exists():
                shots.append(png)
        r = subprocess.run([str(exe), *map(str, shots)], capture_output=True, text=True)
        faces = [d["face"] for d in map(json.loads, r.stdout.splitlines()) if d.get("face")]
    if not faces:
        return "crop=ih:ih"
    cx = sum(f[0] + f[2] / 2 for f in faces) / len(faces)
    cy = sum(f[1] + f[3] / 2 for f in faces) / len(faces)
    fh = max(f[3] for f in faces)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(raw)], capture_output=True, text=True, check=True)
    w, h = (int(v) for v in r.stdout.strip().split(",")[:2])
    side = int(min(h, w, h * fh * FACE_ROOM)) // 2 * 2
    # a little headroom: the face sits slightly above the window's centre, as far as the frame allows
    x = int(min(max(w * cx - side / 2, 0), w - side))
    y = int(min(max(h * cy - side * 0.45, 0), h - side))
    return f"crop={side}:{side}:{x}:{y}"


RNNOISE_URL = ("https://raw.githubusercontent.com/GregorR/rnnoise-models/master/"
               "somnolent-hogwash-2018-09-01/sh.rnnn")


def _rnnoise_model() -> Path | None:
    """GregorR's public RNNoise model (~290 KB) for ffmpeg's arnndn, fetched once into the cache."""
    import os
    m = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "demo-reel" / "rnnoise" / "sh.rnnn"
    if not m.exists():
        m.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["curl", "-sfL", "--max-time", "60", "-o", str(m), RNNOISE_URL])
        if r.returncode != 0 or not m.exists() or not m.read_bytes().startswith(b"rnnoise-nu model"):
            m.unlink(missing_ok=True)
            return None
    return m


def voice_chain() -> str:
    """Speech cleanup like the enhance-speech tools do, before loudness: noise first (else the -16 LUFS
    gain lifts it with the voice), then low cut, gentle compression, presence, de-essing (CASE-B8.2).
    On a quiet laptop-mic take it took the noise floor from -31 to -46 dB at the same loudness."""
    model = _rnnoise_model()
    denoise = f"arnndn=m={model}" if model else "afftdn=nr=18:nf=-50:tn=1"
    return (f"highpass=f=100,{denoise},acompressor=threshold=-24dB:ratio=3:attack=10:release=150:makeup=4,"
            "equalizer=f=3500:t=q:w=1.2:g=3,equalizer=f=250:t=q:w=1:g=-2,deesser=i=0.4,"
            "loudnorm=I=-16:TP=-1.5:LRA=7")


def _compose(film: Path, raw: Path, offset: float, segs: list, dst: Path,
             audio: Path | None = None, audio_offset: float | None = None) -> Path:
    """film + camera window (from raw at offset) + captions + voice (from audio, else raw's own track)."""
    audio = audio or raw
    audio_offset = offset if audio_offset is None else audio_offset
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(film)], capture_output=True, text=True, check=True).stdout)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mask = tmp / "mask.png"
        r = PIP * 0.22
        rr = f"(max({r}-X,0)+max(X-({PIP - 1}-{r}),0))"
        dd = f"(max({r}-Y,0)+max(Y-({PIP - 1}-{r}),0))"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=white:s={PIP}x{PIP}",
                        "-frames:v", "1", "-vf", f"format=gray,geq=lum='if(lte(hypot({rr},{dd}),{r}),255,0)'",
                        str(mask)], check=True)
        inputs = ["-i", str(film), "-ss", f"{offset:.3f}", "-i", str(raw), "-loop", "1", "-i", str(mask),
                  "-ss", f"{audio_offset:.3f}", "-i", str(audio)]
        x, y = 1920 - PIP - PIP_MARGIN, 1080 - PIP - PIP_MARGIN
        g = [f"[1:v]{_face_crop(raw, offset)},scale={PIP}:{PIP},format=yuva420p[cam]", "[2:v]format=gray[m]",
             "[cam][m]alphamerge[pip]", f"[0:v][pip]overlay={x}:{y}:shortest=1,format=yuv420p[v0]"]
        last, n = "v0", 4
        for i, s in enumerate(segs):
            a, b = max(0.0, s["start"]), min(dur, s["end"])
            if b - a < 0.3:
                continue
            png = tmp / f"s{i}.png"
            cards.caption(png, s["text"])
            inputs += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(png)]
            g.append(f"[{last}][{n}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})',format=yuv420p[v{i + 1}]")
            last, n = f"v{i + 1}", n + 1
        g.append(f"[3:a]{voice_chain()}[a]")
        script = tmp / "graph.txt"
        script.write_text(";\n".join(g))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-/filter_complex", str(script), "-map",
                        f"[{last}]", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)],
                       check=True)
    return dst


def narrate(out: Path, camera: str = "0", mic: str = "0") -> list:
    out = Path(out)
    film = _clean_master(out)
    raw = out / "presenter-raw.mov"
    wav = out / "presenter-raw.wav"
    print("Watch the film and talk over it. It plays full screen; press q to stop early.")
    offset, audio_offset = _record(film, raw, wav, camera, mic)
    (out / "presenter-offset.json").write_text(json.dumps({"video": round(offset, 3), "audio": round(audio_offset, 3)}) + "\n")
    # Product names ("aq" came out as "Ack") are hinted with the film's own words.
    tl = timeline.load(out / "timeline.json")
    hint = " ".join([tl.get("intro", {}).get("title", "")] + [c["text"] for c in tl.get("captions", [])]).strip()
    segs = _transcribe(wav, audio_offset, hint)
    (out / "presenter-captions.json").write_text(json.dumps(segs, indent=2, ensure_ascii=False) + "\n")
    x = _compose(film, raw, offset, segs, out / "out" / "x-presenter.mp4", audio=wav, audio_offset=audio_offset)
    readme = out / "out" / "readme-presenter.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(x), "-vf", "scale=1280:-2:flags=lanczos",
                    "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                    str(readme)], check=True)
    print(f"presenter version: {x} and {readme} ({len(segs)} sentences)")
    return segs


if __name__ == "__main__":
    narrate(Path(sys.argv[1]))
