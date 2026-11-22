"""The demo spec (reel.toml): what to show, step by step. Agents write it; people can read it.

    title = "aq"
    subtitle = "A local queue for parallel AI agents"
    url = "github.com/you/aq"            # shown on the last card
    kind = "terminal"                    # terminal | ios | web | mac | animation | card
    accent = ["#1f3b8f", "#1596b8"]      # background gradient
    max_seconds = 30

    [[step]]
    ...                                  # fields depend on kind, see each recorder

A film made of scenes has no kind and no steps; it lists scene specs (paths relative to it),
each an ordinary spec that `reel make <scene>.toml` can also record on its own:

    title = "aq"
    max_seconds = 90
    [[scene]]
    spec = "problem.toml"

Every step may set:
    caption = "..."     # shown while the step plays
    focus   = "..."     # what the camera frames: a pane or region name, or "full"
    hold    = 1.0       # seconds to stay after the step before the next one
"""
from __future__ import annotations

import tomllib
from pathlib import Path

KINDS = ("terminal", "ios", "web", "mac", "animation", "card")
STEPLESS = ("animation", "card")  # steps there only carry narration, so they are optional
DEFAULT_ACCENT = ["#1f3b8f", "#1596b8"]


class SpecError(ValueError):
    pass


def load(path: Path) -> dict:
    path = Path(path).resolve()
    with path.open("rb") as f:
        spec = tomllib.load(f)
    spec["_dir"] = str(path.parent)
    spec["_path"] = str(path)
    if "scene" in spec:
        return _film(spec, path)
    for key in ("title", "kind"):
        if key not in spec:
            raise SpecError(f"{path.name}: missing '{key}'")
    if spec["kind"] not in KINDS:
        raise SpecError(f"{path.name}: kind must be one of {', '.join(KINDS)}")
    steps = spec.get("step", [])
    if not steps and spec["kind"] not in STEPLESS:
        raise SpecError(f"{path.name}: no [[step]]")
    for i, s in enumerate(steps, 1):
        if "caption" in s and not str(s["caption"]).strip():
            raise SpecError(f"{path.name}: step {i} has an empty caption")
    spec.setdefault("accent", DEFAULT_ACCENT)
    spec.setdefault("max_seconds", 30)
    spec.setdefault("step", [])
    return spec


def _film(spec: dict, path: Path) -> dict:
    """A film: scenes in order, each checked to exist and to be an ordinary spec (CASE-C6.1)."""
    if "title" not in spec:
        raise SpecError(f"{path.name}: missing 'title'")
    scenes = []
    for i, sc in enumerate(spec["scene"], 1):
        if "spec" not in sc:
            raise SpecError(f"{path.name}: scene {i} needs spec = \"<file>.toml\"")
        p = (path.parent / sc["spec"]).resolve()
        if not p.exists():
            raise SpecError(f"{path.name}: scene {i}: {sc['spec']} not found")
        with p.open("rb") as f:
            if "scene" in tomllib.load(f):
                raise SpecError(f"{path.name}: scene {i}: {sc['spec']} is itself a film; scenes must be ordinary specs")
        scenes.append(str(p))
    spec["kind"] = "film"
    spec["_scenes"] = scenes
    spec.setdefault("accent", DEFAULT_ACCENT)
    spec.setdefault("max_seconds", 90)
    return spec
