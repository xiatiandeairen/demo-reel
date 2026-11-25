"""Fingerprints: what each stage was made from, so `reel make` redoes only what changed (docs/design.md).

Every stage directory (a scene's take/ and edit/, each cut) holds stamp.json with the digest of its
inputs. A stage whose stored digest equals the current one is reused; otherwise it and every stage after
it are made again.

    take   the scene file without its editing-only fields (say, focus, squeeze, timer), every reel file it
           names (followed through scripts), lang, narration lengths (so with narration on, a new sentence
           is a new take: each step holds until its sentence is spoken)
    edit   the take's stamp, the scene file, the reel's look, and demo-reel's own code
    cut    each scene's edit stamp in order, and demo-reel's own code

The demoed tool lives outside the reel, so a new version of it is invisible here: `reel make --rerecord`.
Recording is never redone because demo-reel's code changed (it costs minutes); editing and joining are.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

CODE = Path(__file__).resolve().parent


def digest(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _files_digest(files) -> str:
    h = hashlib.sha1()
    for f in sorted(files):
        h.update(str(f).encode())
        h.update(Path(f).read_bytes())
    return h.hexdigest()[:16]


def used_files(scene_path: Path, reel_dir: Path) -> set:
    """The scene file and every file in the reel that it names, by file name, followed through what those
    files name (reset -> scripts/setup.sh -> scripts/build.sh). Another scene's files are left out
    (CASE-D2.2), and so is reel.toml (cards are stamped by their own values)."""
    scene_path = Path(scene_path).resolve()
    others = {p.resolve() for p in Path(reel_dir).glob("scenes/*.toml")} | {Path(reel_dir).resolve() / "reel.toml"}
    files = {f.resolve() for f in Path(reel_dir).rglob("*") if f.is_file() and f.resolve() not in others}
    by_name = {}
    for f in files:
        by_name.setdefault(f.name, []).append(f)
    used, todo = {scene_path}, [scene_path]
    while todo:
        text = todo.pop().read_text(errors="replace")
        for name, fs in by_name.items():
            if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", text):
                for f in fs:
                    if f not in used:
                        used.add(f)
                        todo.append(f)
    return used


def code() -> str:
    """demo-reel's own code: editing and joining are redone when it changes."""
    return _files_digest(p for p in CODE.rglob("*") if p.is_file() and p.suffix in (".py", ".js", ".swift"))


EDIT_ONLY = ("say", "focus", "squeeze", "timer")  # step fields only the edit reads


def take(scene: dict, reel: dict) -> str:
    import tomllib
    path = Path(scene["_path"])
    raw = tomllib.loads(path.read_text())
    for s in raw.get("step", []):
        for k in EDIT_ONLY:
            s.pop(k, None)
    files = used_files(path, Path(reel["_dir"])) - {path.resolve()}
    narration = [s.get("_narration") for s in scene.get("step", [])]
    return digest("take", _files_digest(files), raw, reel["lang"], narration)


def read(stage_dir: Path) -> str | None:
    p = Path(stage_dir) / "stamp.json"
    try:
        return json.loads(p.read_text()).get("inputs")
    except (OSError, ValueError):
        return None


def write(stage_dir: Path, value: str) -> None:
    Path(stage_dir).mkdir(parents=True, exist_ok=True)
    (Path(stage_dir) / "stamp.json").write_text(json.dumps({"inputs": value}) + "\n")


def fresh(stage_dir: Path, value: str, *made: str) -> bool:
    """Whether stage_dir was made from inputs `value` and still holds the files `made`."""
    return read(stage_dir) == value and all((Path(stage_dir) / m).exists() for m in made)
