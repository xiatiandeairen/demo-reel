"""Where reel keeps things, following the XDG base directories; nothing is written next to reel.toml.

    $XDG_STATE_HOME/demo-reel/<reel>/   recording, events, timeline, narration, masters, presenter takes:
                                        what `reel plan` / `compose` reuse instead of recording again
    $XDG_DATA_HOME/demo-reel/<reel>/    deliverables: x.mp4, readme.mp4/.gif, clips/, presenter versions,
                                        check.json, sheet.png
    $XDG_CACHE_HOME/demo-reel/          voice and transcription environment, voice clips, models, helpers
    $XDG_CONFIG_HOME/demo-reel/         private.txt (your own sensitive-text patterns)

Defaults: ~/.local/state, ~/.local/share, ~/.cache, ~/.config. <reel> is the spec's folder and file name plus
a short hash of its path (aq-install-6ed752), so two specs never share a directory.
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


def reel_name(spec: dict) -> str:
    """<folder>-<file>-<hash of the spec's path>, e.g. aq-install-6ed752: readable at a glance and
    distinct per spec. The title is only what cards show (a scene titled "aq" for its outro card would
    otherwise share a readable name with the main film)."""
    p = Path(spec["_path"])
    return f"{_slug(p.parent.name)}-{_slug(p.stem)}-{hashlib.sha1(spec['_path'].encode()).hexdigest()[:6]}"


def state_dir(spec: dict) -> Path:
    return state_root() / reel_name(spec)


def deliverables(state: Path) -> Path:
    """The deliverables directory that belongs to a reel's state directory."""
    return data_root() / Path(state).name


def orphans(state: Path | None = None, data: Path | None = None) -> list:
    """State and output directories whose spec no longer exists (or never recorded which spec made them),
    and output directories with no state directory (CASE-D6.1). `reel gc` lists them; `reel gc --yes`
    deletes them."""
    state, data = Path(state or state_root()), Path(data or data_root())
    gone = []
    for st in sorted(state.iterdir()) if state.exists() else []:
        if not st.is_dir() or st.name.startswith("_"):
            continue
        spec_txt = st / "spec.txt"
        if not spec_txt.exists() or not Path(spec_txt.read_text().strip()).exists():
            gone.append(st)
            if (data / st.name).exists():
                gone.append(data / st.name)
    for dd in sorted(data.iterdir()) if data.exists() else []:
        if dd.is_dir() and not (state / dd.name).exists():
            gone.append(dd)
    return gone
