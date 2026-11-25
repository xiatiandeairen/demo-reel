"""The script: what to show, scene by scene. Agents write it with the user; people can read it.

One project can hold several reels, one folder each (docs/design.md):

    <project>/.agents/demo-reel/<name>/
      reel.toml          the whole reel: language, look, which scenes each deliverable uses, cards
      scenes/<id>.toml   a scene to record or render; its id is the file name
      scenes/<id>.html   a drawn animation
      scripts/           the agent's preparation, reset and stand-in scripts

reel.toml:

    lang = "en"                        # en | zh: caption font, line breaking, voice
    narrate = true                     # spoken narration (default off)
    accent = ["#1f3b8f", "#1596b8"]    # optional: background gradient and card colours

    [share]                            # X and YouTube
    scenes = ["result", "problem", "without", "name", "with", "result", "install", "outro"]
    [readme]                           # the README video
    scenes = ["problem", "without", "with", "result", "install", "outro"]
    [gif]                              # the README GIF: one scene, under 30 s
    scene = "with"

    [card.result]                      # a card: drawn, never recorded; its id can be listed like a scene
    lines = ["Builds run: {without} → {with}"]
    [card.result.values]               # each value is a command's output; {files:<scene id>} is the
    without = "wc -l < {files:without}/runs.log"   # folder of files that scene kept (keep_files)

A scene file sets `kind` (terminal, ios, android, web, mac, animation), optionally `reset` (a command the
agent provides, run before the rehearsal and before the recording), its kind's table, and [[step]]s.
Each recorder documents its own fields; ALLOWED below is the complete list.

Values that follow from others are derived here, not written: terminal font size and layout, which panes
are dashboards. A terminal step's camera, unless `focus` says otherwise, frames what changed in the pane
typed in (the whole stage for a step that types nothing).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

KINDS = ("terminal", "ios", "android", "web", "mac", "animation")
LANGS = ("en", "zh")
DEFAULT_ACCENT = ["#1f3b8f", "#1596b8"]

APP_VERBS = ("click", "fill", "type", "key", "scroll", "back")
STEP_COMMON = ("say", "wait", "hold")
ALLOWED = {
    "reel": {"lang", "narrate", "accent", "share", "readme", "gif", "card"},
    "share": {"scenes"}, "readme": {"scenes"}, "gif": {"scene"},
    "card": {"lines", "values", "bars"},
    "scene": {"kind", "reset", "step"},
    "terminal": {"terminal", "pane", "device"},
    "terminal.block": {"workdir", "init", "keep_files"},
    "pane": {"name", "run"},
    "device": {"name", "find"},
    "ios": {"ios"}, "android": {"android"},
    "ios.block": {"app", "device", "settle"}, "android.block": {"app", "device", "settle"},
    "web": {"web"}, "web.block": {"url"},
    "mac": {"mac"}, "mac.block": {"app"},
    "animation": {"animation"}, "animation.block": {"html"},
    "step.terminal": {*STEP_COMMON, "pane", "type", "focus", "squeeze", "timer"},
    "step.app": {*STEP_COMMON, *APP_VERBS},
    "step.animation": {"say"},
}
# Fields that existed before the 2026-11-24 redesign, with what replaces them.
REMOVED = {
    "title": "cards carry their own text: write it in [card.name] or [card.outro] lines",
    "subtitle": "write it in a card's lines",
    "url": "write the link in a card's lines (web scenes: [web] url)",
    "kind": "a reel has no kind; each scenes/<id>.toml has one",
    "max_seconds": "fixed per deliverable: share and readme 90 s, gif 30 s",
    "timer_scale": "derived: the longest timer in the deliverable fills the bar",
    "voice": "set narrate = true; the voice follows lang",
    "speed": "fixed at 1.0",
    "film": "list scenes in [share], [readme] and [gif]",
    "scene": "list scenes in [share], [readme] and [gif]; each is scenes/<id>.toml",
    "clip": "feature clips were removed",
    "intro": "title cards were removed: the film opens on the product",
    "outro": "add a card (e.g. [card.outro]) and list it",
    "gif_max_mb": "fixed at the platform limit, 10 MB",
    "motion_blur": "removed: it ghosted text on zooms",
    "private": "private patterns live only in ~/.config/demo-reel/private.txt",
    "setup": "the agent prepares the environment before reel make; use reset for what reel runs before each take",
    "teardown": "the agent cleans up after reel make",
    "serve": "the agent starts the page server before reel make",
    "font_size": "derived: 40 with four panes or more, else 52",
    "layout": "derived: rows when a device sits beside the terminal, else a grid",
    "typing_ms": "fixed at 45 ms",
    "theme": "fixed",
    "prompt": "fixed at '$ '",
    "open_hold": "derived from the scene's place in each deliverable",
    "rehearse": "every scene is rehearsed",
    "noisy": "derived: a pane with run is a dashboard",
    "caption": "use say",
    "speak": "removed (never used)",
    "keys": "derived from the step's key verb",
    "enter": "a typed command always ends with Enter",
    "allow_fail": "removed (never used); a failing command fails the take",
    "keep_time": "use timer",
    "timeout": "derived from the rehearsal's measured time",
    "press": "use click (tap a target) or key (send a key)",
    "at": "derived: sentences follow each other from the start",
    "status_bar": "always set on simulators, restored afterwards",
    "label": "derived from the url",
    "viewport": "fixed at 1600x900",
    "workdir": "terminal scenes only",
    "launch_args": "the agent launches the app as needed",
    "prepare": "the agent opens the window before reel make",
    "seconds": "derived from the content",
    "fps": "fixed at 30",
}


class SpecError(ValueError):
    pass


def _check(table: dict, allowed: set, where: str) -> None:
    for key in table:
        if key not in allowed:
            why = REMOVED.get(key)
            raise SpecError(f"{where}: '{key}' is not a field" + (f" ({why})" if why else
                            f"; allowed: {', '.join(sorted(allowed))}"))


def _read(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SpecError(f"{path}: {e}") from e


def project_of(reel_dir: Path) -> Path:
    """The project a reel belongs to: the folder holding .agents/, or the reel folder's parent."""
    if reel_dir.parent.name == "demo-reel" and reel_dir.parent.parent.name == ".agents":
        return reel_dir.parent.parent.parent
    return reel_dir.parent


def load(path) -> dict:
    """The reel at <name>/reel.toml with every scene loaded, checked and given its derived values."""
    path = Path(path).resolve()
    if path.is_dir():
        path = path / "reel.toml"
    if not path.exists():
        raise SpecError(f"{path}: not found")
    raw = _read(path)
    where = f"{path.parent.name}/reel.toml"
    _check(raw, ALLOWED["reel"], where)
    lang = raw.get("lang", "en")
    if lang not in LANGS:
        raise SpecError(f"{where}: lang must be one of {', '.join(LANGS)}")
    accent = raw.get("accent", DEFAULT_ACCENT)
    if not (isinstance(accent, list) and len(accent) == 2):
        raise SpecError(f"{where}: accent needs two colours, e.g. [\"#1f3b8f\", \"#1596b8\"]")
    reel = {"_path": str(path), "_dir": str(path.parent), "name": path.parent.name,
            "project": str(project_of(path.parent)), "lang": lang, "narrate": bool(raw.get("narrate", False)),
            "accent": accent, "cards": {}, "scenes": {}, "cuts": {}}

    for cid, card in raw.get("card", {}).items():
        _check(card, ALLOWED["card"], f"{where} [card.{cid}]")
        if not card.get("lines") and not card.get("bars"):
            raise SpecError(f"{where} [card.{cid}]: needs lines or bars")
        reel["cards"][cid] = {"id": cid, "kind": "card", "card": card, "step": [], "accent": accent,
                              "lang": lang, "_dir": str(path.parent), "_path": f"{path}#card.{cid}"}

    scenes_dir = path.parent / "scenes"
    for f in sorted(scenes_dir.glob("*.toml")) if scenes_dir.exists() else []:
        if f.stem in reel["cards"]:
            raise SpecError(f"scenes/{f.name}: its id '{f.stem}' is also a card in reel.toml")
        reel["scenes"][f.stem] = load_scene(f, reel)

    for cut in ("share", "readme"):
        table = raw.get(cut)
        if table is None:
            raise SpecError(f"{where}: missing [{cut}] scenes = [...]")
        _check(table, ALLOWED[cut], f"{where} [{cut}]")
        ids = table.get("scenes") or []
        if not ids:
            raise SpecError(f"{where}: [{cut}] scenes is empty")
        reel["cuts"][cut] = [_known(reel, i, f"{where} [{cut}]") for i in ids]
    gif = raw.get("gif")
    if gif is None or "scene" not in gif:
        raise SpecError(f"{where}: missing [gif] scene = \"<scene id>\"")
    _check(gif, ALLOWED["gif"], f"{where} [gif]")
    if gif["scene"] in reel["cards"]:
        raise SpecError(f"{where} [gif]: the GIF shows a recorded scene, not the card '{gif['scene']}'")
    reel["cuts"]["gif"] = [_known(reel, gif["scene"], f"{where} [gif]")]
    return reel


def _known(reel: dict, sid: str, where: str) -> str:
    if sid not in reel["scenes"] and sid not in reel["cards"]:
        raise SpecError(f"{where}: no scene or card '{sid}' (scenes/{sid}.toml or [card.{sid}])")
    return sid


def scene(reel: dict, sid: str) -> dict:
    """A scene or card of the reel by id."""
    return reel["scenes"].get(sid) or reel["cards"][sid]


def load_scene(path: Path, reel: dict) -> dict:
    raw = _read(path)
    where = f"{path.parent.parent.name}/scenes/{path.name}"
    kind = raw.get("kind")
    if kind not in KINDS:
        raise SpecError(f"{where}: kind must be one of {', '.join(KINDS)}")
    _check(raw, ALLOWED["scene"] | ALLOWED[kind], where)
    block = raw.get(kind, {})
    _check(block, ALLOWED[f"{kind}.block"], f"{where} [{kind}]")
    step_kind = {"terminal": "terminal", "animation": "animation"}.get(kind, "app")
    steps = raw.get("step", [])
    for i, s in enumerate(steps, 1):
        _check(s, ALLOWED[f"step.{step_kind}"], f"{where} step {i}")
        if "say" in s and not str(s["say"]).strip():
            raise SpecError(f"{where} step {i}: say is empty")
        if step_kind == "app" and len([v for v in APP_VERBS if v in s]) > 1:
            raise SpecError(f"{where} step {i}: one action per step ({', '.join(v for v in APP_VERBS if v in s)})")
    if kind != "animation" and not steps:
        raise SpecError(f"{where}: no [[step]]")
    if steps and not steps[0].get("say"):
        raise SpecError(f"{where} step 1: needs say (captions run from the first step; later steps may leave it out)")
    for need, kinds in (("app", ("ios", "android", "mac")), ("device", ("ios", "android")), ("url", ("web",)),
                        ("html", ("animation",))):
        if kind in kinds and need not in block:
            raise SpecError(f"{where}: [{kind}] needs {need}")

    sc = {**raw, "id": path.stem, "_path": str(path), "_dir": str(path.parent), "accent": reel["accent"],
          "lang": reel["lang"], "title": path.stem, "step": steps}
    if reel["narrate"]:
        sc["voice"] = True  # the voice itself follows lang (reel/voice.py)
    if kind == "terminal":
        _terminal(sc, where)
    return sc


def _terminal(sc: dict, where: str) -> None:
    panes = sc.get("pane") or [{"name": "main"}]
    for p in panes:
        _check(p, ALLOWED["pane"], f"{where} [[pane]]")
        if "name" not in p:
            raise SpecError(f"{where}: every [[pane]] needs a name")
        p["noisy"] = "run" in p
    names = [p["name"] for p in panes]
    devices = sc.get("device", [])
    for d in devices:
        _check(d, ALLOWED["device"], f"{where} [[device]]")
        if "name" not in d or "find" not in d:
            raise SpecError(f"{where}: every [[device]] needs name and find")
    term = sc.setdefault("terminal", {})
    term["font_size"] = 40 if len(panes) >= 4 else 52
    term["layout"] = "even-vertical" if devices else "tiled"
    targets = set(names) | {d["name"] for d in devices} | {"full"}
    for i, s in enumerate(sc["step"], 1):
        if "pane" in s and s["pane"] not in names:
            raise SpecError(f"{where} step {i}: no pane '{s['pane']}' (panes: {', '.join(names)})")
        focus = s.get("focus", [])  # default: the pane typed in, framed tight on what changed
        for f in [focus] if isinstance(focus, str) else focus:
            if f not in targets:
                raise SpecError(f"{where} step {i}: focus '{f}' is not a pane or device ({', '.join(sorted(targets))})")
    sc["pane"] = panes
