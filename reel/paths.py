"""Where reel keeps things, following the XDG base directories (docs/design.md, "流程和存储").

    $XDG_STATE_HOME/demo-reel/<reel>/   scenes/<id>/rehearsal.json, take/, edit/; cuts/<cut>/; presenter/
    $XDG_DATA_HOME/demo-reel/<reel>/    share.mp4, readme.mp4, presenter versions, report.json, sheets, leaks/
    $XDG_CACHE_HOME/demo-reel/          voice clips, voice and transcription environments, models, helpers
    $XDG_CONFIG_HOME/demo-reel/         private.txt (your own sensitive-text patterns)
    <project>/assets/<name>.gif         the README GIF

Defaults: ~/.local/state, ~/.local/share, ~/.cache, ~/.config. <reel> is the project's folder name, the
reel's name and a short hash of the reel's path (agent-quay-cli-7cb4f8): readable, and distinct per
worktree, since each worktree's path differs.
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


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-") or "demo"


def reel_name(reel: dict) -> str:
    h = hashlib.sha1(reel["_path"].encode()).hexdigest()[:6]
    return f"{_slug(Path(reel['project']).name)}-{_slug(reel['name'])}-{h}"


def state_dir(reel: dict) -> Path:
    return state_root() / reel_name(reel)


def scene_dir(reel: dict, sid: str) -> Path:
    return state_dir(reel) / "scenes" / sid


def take_dir(reel: dict, sid: str) -> Path:
    return scene_dir(reel, sid) / "take"


def edit_dir(reel: dict, sid: str) -> Path:
    return scene_dir(reel, sid) / "edit"


def cut_dir(reel: dict, cut: str) -> Path:
    return state_dir(reel) / "cuts" / cut


def data_dir(reel: dict) -> Path:
    return data_root() / reel_name(reel)


def gif_path(reel: dict) -> Path:
    return Path(reel["project"]) / "assets" / f"{reel['name']}.gif"
