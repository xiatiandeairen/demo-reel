"""reel: record, plan, compose, export and check product demos.

    reel make <reel.toml> [--out DIR]     all steps below
    reel record <reel.toml> [--out DIR]   stage.mp4 + events.json
    reel plan <reel.toml> [--out DIR]     timeline.json (camera, cuts, captions)
    reel compose <DIR>                    master.mp4
    reel export <DIR>                     x.mp4, readme.mp4, readme.gif in DIR/out
    reel check <DIR>                      platform limits, first frame, sensitive text
    reel sync <DIR>                       logged step times vs visible changes, camera coverage
    reel sheet <DIR>                      contact sheet over the whole x.mp4, for review
    reel narrate <DIR> [--camera 0] [--mic 0]   talk over the film: adds your camera, voice, captions
    reel test [--integration]             the case suite
    reel gc [--yes]                       list state and outputs whose spec is gone; --yes deletes them

Nothing is written next to reel.toml: state goes to $XDG_STATE_HOME/demo-reel/<reel>/, deliverables to
$XDG_DATA_HOME/demo-reel/<reel>/ (see reel/paths.py). <DIR> may be either that state directory or reel.toml.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _out(spec: dict, out: str | None) -> Path:
    from . import paths
    return Path(out) if out else paths.state_dir(spec)


def _make_film_scene(path: str) -> None:
    """A film's scene: recorded again only when something it uses changed (REEL_RERECORD=always forces it);
    cards are drawn on every compose anyway."""
    import os
    from .film import up_to_date
    from .rehearse import fingerprint
    sc = spec_mod_load(path)
    out = paths_state(sc)
    fp = fingerprint(Path(path))
    if sc["kind"] != "card" and os.environ.get("REEL_RERECORD") != "always" and up_to_date(out, fp):
        print(f"  unchanged since its last recording: reused ({out.name})")
        return
    (out / "recorded.json").unlink(missing_ok=True)
    _make_scene(sc, out)
    (out / "recorded.json").write_text(json.dumps({"fingerprint": fp}) + "\n")


def spec_mod_load(path):
    from . import spec as spec_mod
    return spec_mod.load(path)


def paths_state(spec: dict) -> Path:
    from . import paths
    return paths.state_dir(spec)


def _resolve(arg: str) -> Path:
    """A reel's state directory, given that directory or its reel.toml."""
    if arg.endswith(".toml"):
        from . import paths, spec as spec_mod
        return paths.state_dir(spec_mod.load(arg))
    return Path(arg)


def _record(spec, out):
    kind = spec["kind"]
    if kind == "terminal":
        from .record_terminal import record
    elif kind == "ios":
        from .record_ios import record
    elif kind == "web":
        from .record_web import record
    elif kind == "animation":
        from .record_animation import record
    elif kind == "card":
        from .record_card import record
    else:
        from .record_mac import record
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.txt").write_text(spec["_path"] + "\n")
    if kind == "terminal" and spec.get("terminal", {}).get("rehearse", True):
        from .rehearse import rehearse
        rehearse(spec, out)  # run once unrecorded first: a recording that fails costs minutes
    from .voice import prepare
    prepare(spec, out)  # narration first: its length sets how long each step holds
    return record(spec, out)


def _compose_all(out: Path) -> None:
    """scene.mp4 (silent, no fade: what a film joins) and narration.json; master.mp4 (faded out, with
    narration mixed in, if any); clips/<name>.mp4 for each feature clip."""
    from . import timeline as tlm
    from .compose_ffmpeg import XFADE, add_narration, compose, fade_end
    tl_path = out / "timeline.json"
    tl = tlm.load(tl_path)
    window = tuple(tl["film"]) if tl.get("film") else None
    keep = tl["keep"]
    if window:
        keep = [[max(a, window[0]), min(b, window[1])] for a, b in keep if min(b, window[1]) - max(a, window[0]) > 0.05]
    narration = [n for n in tl.get("narration", []) if tlm.output_time(keep, n["start"]) is not None]
    lead = tl["intro"]["seconds"] - XFADE if tl.get("intro") else 0.0
    items = [{"wav": n["wav"], "at": round(lead + tlm.output_time(keep, n["start"]), 3)} for n in narration]
    scene = out / "scene.mp4"
    compose(tl_path, scene, window=window, with_cards=True, fade_out=False)
    (out / "narration.json").write_text(json.dumps(items, indent=2) + "\n")
    master = out / "master.mp4"
    if items:
        silent = out / "master-silent.mp4"
        fade_end(scene, silent)
        add_narration(silent, [(out / n["wav"], n["at"]) for n in items], master)
    else:
        fade_end(scene, master)
    print(f"composed {master}")
    for c in tl.get("clips", []):
        dst = out / "clips" / f"{c['name']}.mp4"
        dst.parent.mkdir(exist_ok=True)
        compose(tl_path, dst, window=(c["start"], c["end"]), loop=True)
        print(f"composed {dst}")


def _make_scene(spec: dict, out: Path) -> None:
    """Records, plans and composes one ordinary spec (a scene, or a film of its own)."""
    from .planner import plan
    _record(spec, out)
    print(f"recorded {out / 'stage.mp4'}")
    print(f"planned {plan(spec, out)}")
    _compose_all(out)


def _finish(out: Path, spec: dict | None, steps=("compose", "export", "check")) -> int:
    from .check import check, print_report
    from .export import export
    if spec and spec["kind"] == "film":
        (out / "spec.txt").parent.mkdir(parents=True, exist_ok=True)
        (out / "spec.txt").write_text(spec["_path"] + "\n")
        if "compose" in steps:
            from .film import stitch
            narrated = stitch(spec, out, _make_scene)
            spec = {**spec, "voice": spec.get("voice") or narrated}
        elif "check" in steps and (out / "film.json").exists():
            spec = {**spec, "voice": spec.get("voice") or json.loads((out / "film.json").read_text()).get("narrated")}
    elif "compose" in steps:
        _compose_all(out)
    if "export" in steps:
        export(out, spec)
    if "check" in steps:
        report = check(out, spec)
        print_report(report)
        return 0 if report["ok"] else 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="reel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("make", "record", "plan"):
        s = sub.add_parser(name)
        s.add_argument("spec")
        s.add_argument("--out")
    for name in ("compose", "export", "check", "sync", "sheet"):
        sub.add_parser(name).add_argument("dir")
    s = sub.add_parser("narrate")
    s.add_argument("dir")
    s.add_argument("--camera", default="0")
    s.add_argument("--mic", default="0")
    sub.add_parser("gc").add_argument("--yes", action="store_true")
    s = sub.add_parser("test")
    s.add_argument("--integration", action="store_true")
    a = p.parse_args(argv)

    from . import spec as spec_mod
    if a.cmd == "test":
        env_flag = ["env", "REEL_INTEGRATION=1"] if a.integration else []
        return subprocess.call([*env_flag, sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT)
    if a.cmd == "gc":
        import shutil
        from . import paths
        gone = paths.orphans()
        size = lambda p: sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        for p in gone:
            print(f"{size(p) / 1e6:8.1f} MB  {p}")
        print(f"{len(gone)} directories, {sum(map(size, gone)) / 1e6:.1f} MB" if gone else "nothing to remove")
        if gone and a.yes:
            for p in gone:
                shutil.rmtree(p)
            print("removed")
        elif gone:
            print("run reel gc --yes to remove them")
        return 0
    if a.cmd == "narrate":
        from .narrate import narrate
        narrate(_resolve(a.dir), a.camera, a.mic)
        return 0
    if a.cmd == "sheet":
        from .check import probe
        from . import paths
        d = paths.deliverables(_resolve(a.dir))
        dur = probe(d / "x.mp4")["duration"]
        sheet = d / "sheet.png"
        # 24 cells spread over the whole film, so the ending is reviewed too.
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(d / "x.mp4"), "-vf",
                        f"fps=24/{dur:.3f},scale=480:-1,tile=4x6", "-frames:v", "1", "-update", "1", str(sheet)],
                       check=True)
        print(f"sheet {sheet} (24 frames, one every {dur / 24:.1f} s)")
        return 0
    if a.cmd == "sync":
        from .planner import framing_report, sync_report
        print(json.dumps({"sync": sync_report(_resolve(a.dir)), "framing": framing_report(_resolve(a.dir))},
                         indent=2, ensure_ascii=False))
        return 0
    if a.cmd in ("make", "record", "plan"):
        spec = spec_mod.load(a.spec)
        out = _out(spec, a.out)
        if spec["kind"] == "film":
            if a.cmd != "make":
                print("a film has no recording of its own: reel make <film.toml>, or record a scene's own spec")
                return 2
            from .film import make_all
            make_all(spec["_scenes"], _make_film_scene)
            return _finish(out, spec)
        if a.cmd in ("make", "record"):
            _record(spec, out)
            print(f"recorded {out / 'stage.mp4'}")
        if a.cmd in ("make", "plan"):
            from .planner import plan
            print(f"planned {plan(spec, out)}")
        if a.cmd != "make":
            return 0
        code = _finish(out, spec)
        if (out / "scene.mp4").exists():  # composed: a film may reuse this recording while its inputs stay the same
            from .rehearse import fingerprint
            (out / "recorded.json").write_text(json.dumps({"fingerprint": fingerprint(Path(spec["_path"]))}) + "\n")
        return code
    out = _resolve(a.dir)
    spec_file = out / "spec.txt"
    if a.dir.endswith(".toml"):
        spec = spec_mod.load(a.dir)
    else:
        spec = spec_mod.load(spec_file.read_text().strip()) if spec_file.exists() else None
    return _finish(out, spec, steps=(a.cmd,))


if __name__ == "__main__":
    sys.exit(main())
