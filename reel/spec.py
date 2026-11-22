"""The demo spec (reel.toml): what to show, step by step. Agents write it; people can read it.

    title = "aq"
    subtitle = "A local queue for parallel AI agents"
    url = "github.com/you/aq"            # shown on the last card
    kind = "terminal"                    # terminal | ios | web | mac
    accent = ["#1f3b8f", "#1596b8"]      # background gradient
    max_seconds = 30

    [[step]]
    ...                                  # fields depend on kind, see each recorder

Every step may set:
    caption = "..."     # shown while the step plays
    focus   = "..."     # what the camera frames: a pane or region name, or "full"
    hold    = 1.0       # seconds to stay after the step before the next one
"""
from __future__ import annotations

import tomllib
from pathlib import Path

KINDS = ("terminal", "ios", "web", "mac")
DEFAULT_ACCENT = ["#1f3b8f", "#1596b8"]


class SpecError(ValueError):
    pass


def load(path: Path) -> dict:
    path = Path(path).resolve()
    with path.open("rb") as f:
        spec = tomllib.load(f)
    spec["_dir"] = str(path.parent)
    spec["_path"] = str(path)
    for key in ("title", "kind"):
        if key not in spec:
            raise SpecError(f"{path.name}: missing '{key}'")
    if spec["kind"] not in KINDS:
        raise SpecError(f"{path.name}: kind must be one of {', '.join(KINDS)}")
    steps = spec.get("step", [])
    if not steps:
        raise SpecError(f"{path.name}: no [[step]]")
    for i, s in enumerate(steps, 1):
        if "caption" in s and not str(s["caption"]).strip():
            raise SpecError(f"{path.name}: step {i} has an empty caption")
    spec.setdefault("accent", DEFAULT_ACCENT)
    spec.setdefault("max_seconds", 30)
    return spec
