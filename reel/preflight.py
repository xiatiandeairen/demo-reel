"""Preflight: is everything the reel needs ready, before anything runs (docs/design.md).

The agent prepares the environment and the devices; this names what is missing in a few seconds, so a
take never starts half-ready. Each row: (ok, what, detail and how to fix it).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import cards

TOOLS = {
    "terminal": ["vhs", "tmux"],
    "ios": ["agent-device", "xcrun"],
    "android": ["agent-device", "adb"],
    "web": ["agent-browser"],
    "mac": ["agent-desktop", "screencapture"],
    "animation": ["agent-browser"],
}


def device_id(value: str) -> str:
    """A device field ("$REEL_SIM" or a literal id) with environment variables filled in."""
    return os.path.expandvars(str(value)).strip()


def _booted_simulators() -> str:
    r = subprocess.run(["xcrun", "simctl", "list", "devices"], capture_output=True, text=True)
    return r.stdout


def check(reel: dict) -> list:
    rows = []
    kinds = {sc["kind"] for sc in reel["scenes"].values()}
    need = ["ffmpeg", "ffprobe"] + sorted({t for k in kinds for t in TOOLS[k]})
    missing = [t for t in need if not shutil.which(t)]
    if "terminal" in kinds and not any(Path(c).exists() for c in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash")):
        missing.append("bash 5 (brew install bash)")
    try:
        cards.chrome()
    except RuntimeError:
        missing.append("Google Chrome")
    if reel["narrate"] and not shutil.which("uv") and not (Path.home() / ".cache/demo-reel/tts-venv/bin/python").exists():
        missing.append("uv (brew install uv), for narration")
    rows.append((not missing, "tools", f"missing {', '.join(missing)}" if missing else ", ".join(need)))

    sims = None
    for sid, sc in reel["scenes"].items():
        if sc["kind"] == "terminal" and not sc.get("reset"):
            from .record_terminal import workdir
            work = workdir(sc)
            if not work.is_dir():
                rows.append((False, "workdir", f"{sid}: {work} does not exist; prepare it before reel make, "
                                               "or give the scene a reset that does"))
        if sc["kind"] in ("ios", "android"):
            block = sc[sc["kind"]]
            dev = device_id(block["device"])
            if not dev or "$" in dev:
                rows.append((False, "device", f"{sid}: device {block['device']!r} is not set; export it with the "
                                              "device's id before reel make"))
                continue
            if sc["kind"] == "ios":
                sims = sims if sims is not None else _booted_simulators()
                line = next((l for l in sims.splitlines() if dev in l), None)
                if line and "(Booted)" not in line:
                    rows.append((False, "device", f"{sid}: simulator {dev} is not booted → xcrun simctl boot {dev}"))
            else:
                r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
                if f"{dev}\tdevice" not in r.stdout:
                    rows.append((False, "device", f"{sid}: Android device {dev} is not connected (adb devices)"))
    if len(rows) == 1 or all(r[1] != "device" for r in rows):
        n = sum(1 for sc in reel["scenes"].values() if sc["kind"] in ("ios", "android"))
        if n:
            rows.append((True, "devices", f"{n} set"))
    return rows
