"""Narration: one spoken sentence per step that has `say`, when the reel sets narrate = true.

The voice follows the reel's lang (VOICES below); Kokoro runs locally on Apple Silicon through mlx-audio.

Kokoro lives in its own virtual environment (~/.cache/demo-reel/tts-venv), created on first use
with uv, so its dependencies never touch the project. Clips are cached by model, voice and text.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from . import paths

VENV = paths.cache_root() / "tts-venv"
# Per language: (model, voice, Kokoro language code). English: Kokoro v1, am_michael passed the
# 2026-11-22 listening test. Chinese: Kokoro v1.1-zh (1038lab's MLX conversion of hexgrad/Kokoro-82M-v1.1-zh),
# zf_001 chosen by listening on 2026-11-25 over v1's zf_xiaobei / zm_yunxi, which VOICES.md grades D.
VOICES = {
    "en": ("prince-canuma/Kokoro-82M", "am_michael", "a"),
    "zh": ("1038lab/Kokoro-82M-zh-MLX", "zf_001", "z"),
}


class VoiceError(RuntimeError):
    pass


def _env() -> dict:
    # misaki fetches its English model with uv at first use; uv needs the venv to be active.
    return {**os.environ, "VIRTUAL_ENV": str(VENV), "PATH": f"{VENV / 'bin'}:{os.environ['PATH']}"}


def ensure() -> Path:
    py = VENV / "bin" / "python"
    if py.exists():
        return py
    if not shutil.which("uv"):
        raise VoiceError("narration needs uv to install Kokoro: brew install uv")
    subprocess.run(["uv", "venv", "-q", "--python", "3.12", str(VENV)], check=True)
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(py), "mlx-audio", "misaki[en,zh]"], check=True)
    return py


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def synth(text: str, lang: str, cache: Path) -> Path:
    """One sentence to a wav in the reel's language (cached by model, voice and text); returns its path."""
    model, voice, code = VOICES[lang]
    key = hashlib.sha1(f"{model}|{voice}|1.0|{text}".encode()).hexdigest()[:16]  # same keys as before the per-language voices
    cache.mkdir(parents=True, exist_ok=True)
    wav = cache / f"{key}.wav"
    if wav.exists():
        return wav
    py = ensure()
    tmp = cache / f"tmp-{key}"
    tmp.mkdir(exist_ok=True)
    r = subprocess.run([str(py), "-m", "mlx_audio.tts.generate", "--model", model, "--text", text, "--voice", voice,
                        "--lang_code", code, "--output_path", str(tmp),
                        "--file_prefix", "say", "--join_audio", "--audio_format", "wav"],
                       capture_output=True, text=True, env=_env())
    made = sorted(tmp.glob("say*.wav"))
    if r.returncode != 0 or not made:
        raise VoiceError(f"Kokoro failed for {text!r}: {(r.stderr or r.stdout).strip()[-300:]}")
    made[0].replace(wav)
    shutil.rmtree(tmp, ignore_errors=True)
    return wav


def prepare(spec: dict) -> None:
    """Synthesises every step's sentence before recording and stores its length on the step as
    `_narration` (and the cached clip as `_narration_wav`), so recorders hold each step until its sentence
    has been spoken (CASE-B7.1). Clips stay in the cache; nothing is copied into the reel's state."""
    if not spec.get("voice"):
        return
    cache = paths.cache_root() / "voice"
    for s in spec["step"]:
        if not s.get("say"):
            continue
        wav = synth(s["say"], spec["lang"], cache)
        s["_narration"] = round(duration(wav), 3)
        s["_narration_wav"] = str(wav)
