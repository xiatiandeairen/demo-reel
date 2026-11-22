"""Where reel keeps things, following the XDG base directories; nothing is written next to reel.toml.

    $XDG_STATE_HOME/demo-reel/<reel>/   recording, events, timeline, narration, masters, presenter takes:
                                        what `reel plan` / `compose` reuse instead of recording again
    $XDG_DATA_HOME/demo-reel/<reel>/    deliverables: x.mp4, readme.mp4/.gif, clips/, presenter versions,
                                        check.json, sheet.png
    $XDG_CACHE_HOME/demo-reel/          voice and transcription environment, voice clips, models, helpers
    $XDG_CONFIG_HOME/demo-reel/         private.txt (your own sensitive-text patterns)

Defaults: ~/.local/state, ~/.local/share, ~/.cache, ~/.config. <reel> is the film's title plus a short
hash of the spec's path, so two projects with a film of the same name never share a directory.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _home(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default) / "demo-reel"


def state_root() -> Path:
    return _home("XDG_STATE_HOME", ".local/state")


def data_root() -> Path:
    return _home("XDG_DATA_HOME", ".local/share")


def cache_root() -> Path:
    return _home("XDG_CACHE_HOME", ".cache")


def config_root() -> Path:
    return _home("XDG_CONFIG_HOME", ".config")


def reel_name(spec: dict) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in spec["title"].lower()).strip("-") or "demo"
    return f"{slug}-{hashlib.sha1(spec['_path'].encode()).hexdigest()[:6]}"


def state_dir(spec: dict) -> Path:
    return state_root() / reel_name(spec)


def deliverables(state: Path) -> Path:
    """The deliverables directory that belongs to a reel's state directory."""
    return data_root() / Path(state).name
