"""reel: record, plan, compose, export and check product demos.

    reel make <reel.toml> [--out DIR]     all steps below
    reel record <reel.toml> [--out DIR]   stage.mp4 + events.json
    reel plan <reel.toml> [--out DIR]     timeline.json (camera, cuts, captions)
    reel compose <DIR>                    master.mp4
    reel export <DIR>                     x.mp4, readme.mp4, readme.gif in DIR/out
    reel check <DIR>                      platform limits, first frame, sensitive text
    reel sync <DIR>                       logged step times vs visible changes, camera coverage
    reel sheet <DIR>                      contact sheet over the whole x.mp4, for review
    reel test [--integration]             the case suite

The default output directory is .reel/ next to reel.toml.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _out(spec_path: str, out: str | None) -> Path:
    return Path(out) if out else Path(spec_path).resolve().parent / ".reel"


def _record(spec, out):
    kind = spec["kind"]
    if kind == "terminal":
        from .record_terminal import record
    elif kind == "ios":
        from .record_ios import record
    elif kind == "web":
        from .record_web import record
    else:
        from .record_mac import record
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.txt").write_text(spec["_path"] + "\n")
    return record(spec, out)


def _finish(out: Path, spec: dict | None, steps=("compose", "export", "check")) -> int:
    from .check import check, print_report
    from .compose_ffmpeg import compose
    from .export import export
    if "compose" in steps:
        print(f"composed {compose(out / 'timeline.json', out / 'master.mp4')}")
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
    s = sub.add_parser("test")
    s.add_argument("--integration", action="store_true")
    a = p.parse_args(argv)

    from . import spec as spec_mod
    if a.cmd == "test":
        env_flag = ["env", "REEL_INTEGRATION=1"] if a.integration else []
        return subprocess.call([*env_flag, sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT)
    if a.cmd == "sheet":
        from .check import probe
        d = Path(a.dir) / "out"
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
        print(json.dumps({"sync": sync_report(Path(a.dir)), "framing": framing_report(Path(a.dir))},
                         indent=2, ensure_ascii=False))
        return 0
    if a.cmd in ("make", "record", "plan"):
        spec = spec_mod.load(a.spec)
        out = _out(a.spec, a.out)
        if a.cmd in ("make", "record"):
            _record(spec, out)
            print(f"recorded {out / 'stage.mp4'}")
        if a.cmd in ("make", "plan"):
            from .planner import plan
            print(f"planned {plan(spec, out)}")
        return _finish(out, spec) if a.cmd == "make" else 0
    out = Path(a.dir)
    spec_file = out / "spec.txt"
    spec = spec_mod.load(spec_file.read_text().strip()) if spec_file.exists() else None
    return _finish(out, spec, steps=(a.cmd,))


if __name__ == "__main__":
    sys.exit(main())
