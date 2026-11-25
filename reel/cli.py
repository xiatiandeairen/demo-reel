"""reel: turn a reel (script) into share.mp4, readme.mp4 and the README GIF (docs/design.md).

    reel make <reel.toml> [--rerecord]   preflight → narration → rehearsal → take → edit → cards → cuts
                                         → export → checks → contact sheets; redoes only what changed
                                         (--rerecord: record every scene again, e.g. after the demoed tool
                                         was upgraded, which reel cannot see)
    reel narrate <reel.toml> [--cut share|readme] [--camera 0] [--mic 0]
                                         you, in your own terminal: talk over the film; adds your camera,
                                         voice and captions as <cut>-presenter.mp4

<reel.toml> is <project>/.agents/demo-reel/<name>/reel.toml (or its folder). Nothing is written next to
it except the GIF, <project>/assets/<name>.gif; the rest goes to the XDG folders (reel/paths.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths, spec as spec_mod, stamp

CUTS = ("share", "readme", "gif")


class Failed(RuntimeError):
    """A stage failed: printed as FAIL <stage> with the scene, the reason and what to do."""

    def __init__(self, stage: str, scene: str | None, reason: str, todo: str = ""):
        super().__init__(reason)
        self.stage, self.scene, self.reason, self.todo = stage, scene, reason, todo


def _say(line: str = "") -> None:
    print(line, flush=True)


def _run_reset(reel: dict, sc: dict) -> None:
    if not sc.get("reset"):
        return
    env = dict(os.environ)
    if sc["kind"] == "terminal":
        from .record_terminal import workdir
        env["REEL_WORK"] = str(workdir(sc))
    r = subprocess.run(["bash", "-c", sc["reset"]], cwd=reel["_dir"], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        said = "\n".join(x.strip() for x in (r.stdout, r.stderr) if x.strip())[-600:] or "(it printed nothing)"
        raise Failed("reset", sc["id"], f"`{sc['reset']}` exited with {r.returncode}:\n{said}",
                     "fix the reset command, then reel make")


def _recorder(kind: str):
    from importlib import import_module
    return import_module(f".record_{'ios' if kind == 'android' else kind}", __package__).record


def _take(reel: dict, sc: dict, rerecord: bool) -> tuple:
    """(stamp, line): the scene's take, recorded again only when its inputs changed."""
    from . import voice
    from .record_terminal import RecordError
    voice.prepare(sc)
    st = stamp.take(sc, reel)
    sid, td = sc["id"], paths.take_dir(reel, sc["id"])
    if not rerecord and stamp.fresh(td, st, "stage.mp4", "events.json"):
        return st, "reused (unchanged)"
    parts = []
    try:
        if sc["kind"] == "terminal":
            from .rehearse import rehearse, timeout
            _run_reset(reel, sc)
            rep = rehearse(sc, paths.scene_dir(reel, sid), st)
            for s, secs in zip(sc["step"], rep["seconds"]):
                s["_timeout"] = timeout(secs)
            parts.append("rehearse reused" if rep.get("reused") else f"rehearse ok {rep['total']:.0f} s")
        _run_reset(reel, sc)
        shutil.rmtree(td, ignore_errors=True)
        td.mkdir(parents=True)
        _recorder(sc["kind"])(sc, td)
    except RecordError as e:
        stage = "rehearse" if "rehearsal" in str(e) else "record"
        raise Failed(stage, sid, str(e), "fix the demo or its environment (reel does not change the project), "
                                         "then reel make") from e
    stamp.write(td, st)
    ev = json.loads((td / "events.json").read_text())
    parts.append(f"record ok {ev['stage']['duration']:.0f} s")
    return st, " · ".join(parts)


def _narration(edit: Path) -> list:
    from . import timeline as tlm
    tl = tlm.load(edit / "timeline.json")
    return [(n["wav"], round(tlm.output_time(tl["keep"], n["start"]), 3)) for n in tl.get("narration", [])
            if tlm.output_time(tl["keep"], n["start"]) is not None]


def _edit(reel: dict, sc: dict, take_stamp: str, scale: float, take: Path | None = None) -> tuple:
    from .compose_ffmpeg import compose
    from .planner import plan
    ed = paths.edit_dir(reel, sc["id"])
    src = Path(sc["_path"].split("#")[0])
    es = stamp.digest("edit", take_stamp, src.read_text() if src.exists() else "", reel["accent"], scale,
                      stamp.code(), [s.get("_narration_wav") for s in sc.get("step", [])])
    if stamp.fresh(ed, es, "scene.mp4", "timeline.json"):
        return es, "reused"
    plan(sc, take or paths.take_dir(reel, sc["id"]), ed, scale)
    compose(ed / "timeline.json", ed / "scene.mp4", with_cards=True, fade_out=False)
    stamp.write(ed, es)
    return es, "edit ok"


def _card(reel: dict, sc: dict) -> tuple:
    from . import record_card
    sc = {**sc, "_scenes": paths.state_dir(reel) / "scenes"}
    try:
        resolved = record_card.resolve(sc)
    except record_card.CardError as e:
        raise Failed("card", sc["id"], str(e), "check the command against the scene's kept files, then reel make") from e
    ed = paths.edit_dir(reel, sc["id"])
    cs = stamp.digest("card", sc["card"], resolved, reel["accent"], stamp.code())
    if stamp.fresh(ed, cs, "scene.mp4", "timeline.json"):
        return cs, "reused"
    shutil.rmtree(ed, ignore_errors=True)
    record_card.record(sc, ed, resolved)
    _edit_card(reel, sc, ed)
    stamp.write(ed, cs)
    lines = resolved[0] or [f"{g['title']}: " + ", ".join(i["text"] for i in g["items"]) for g in resolved[1]]
    return cs, "card ok  " + " · ".join(lines)


def _edit_card(reel: dict, sc: dict, ed: Path) -> None:
    from .compose_ffmpeg import compose
    from .planner import plan
    plan(sc, ed, ed)
    compose(ed / "timeline.json", ed / "scene.mp4", with_cards=True, fade_out=False)


def _sheet(video: Path, png: Path) -> str:
    from .check import probe
    dur = probe(video)["duration"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    f"fps=24/{dur:.3f},scale=480:-1,tile=4x6", "-frames:v", "1", "-update", "1", str(png)], check=True)
    return f"24 frames, one every {dur / 24:.1f} s"


def _sha(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _place_gif(reel: dict, pending: Path, report: dict, previous: dict) -> str:
    """Writes the GIF into the project's assets/, refusing to replace a file demo-reel did not write."""
    dst = paths.gif_path(reel)
    if dst.exists():
        mine = previous.get("gif_written", {})
        if mine.get("path") != str(dst) or mine.get("sha1") != _sha(dst):
            raise Failed("export", None, f"{dst} exists and was not written by demo-reel",
                         "move or rename that file (or choose another reel name), then reel make")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(pending, dst)
    report["gif_written"] = {"path": str(dst), "sha1": _sha(dst)}
    return str(dst)


def make(reel_path: str, rerecord: bool = False) -> int:
    from . import preflight
    from .check import check, print_report, probe
    from .export import export
    from .planner import timed_runs, timer_scale
    try:
        reel = spec_mod.load(reel_path)
    except spec_mod.SpecError as e:
        _say(f"FAIL script\n  {e}\n  → fix the script, then reel make")
        return 1
    rows = preflight.check(reel)
    if not all(ok for ok, _, _ in rows):
        _say("preflight  FAIL")
        for ok, what, detail in rows:
            _say(f"  {'ok  ' if ok else 'FAIL'}  {what:<9}{detail}")
        _say("\nnothing recorded")
        return 1
    _say("preflight  ok   " + " · ".join(f"{w} {d}" if w != "tools" else "tools ready" for ok, w, d in rows))
    ids = list(dict.fromkeys(i for c in CUTS for i in reel["cuts"][c]))
    scenes = [i for i in ids if i in reel["scenes"]]
    cards = [i for i in ids if i in reel["cards"]]
    total = len(scenes) + len(cards)
    edits, done = {}, []
    try:
        takes = {}
        for k, sid in enumerate(scenes, 1):
            sc = reel["scenes"][sid]
            takes[sid], line = _take(reel, sc, rerecord)
            done.append(sid)
            _say(f"scene {k}/{total}  {sid:<12} {line}")
        scale = timer_scale([r for sid in scenes for r in timed_runs(reel["scenes"][sid], paths.take_dir(reel, sid))])
        for sid in scenes:
            edits[sid], _ = _edit(reel, reel["scenes"][sid], takes[sid], scale)
        for k, cid in enumerate(cards, len(scenes) + 1):
            edits[cid], line = _card(reel, reel["cards"][cid])
            _say(f"scene {k}/{total}  {cid:<12} {line}")
    except Failed as f:
        _fail(f, done)
        return 1

    cut_stamps, masters, lines = {}, {}, []
    from .film import stitch
    for cut in CUTS:
        ids_ = reel["cuts"][cut]
        cs = stamp.digest("cut", cut, [edits[i] for i in ids_], stamp.code())
        cd = paths.cut_dir(reel, cut)
        if not stamp.fresh(cd, cs, "master.mp4", "cut.json"):
            stitch([(i, paths.edit_dir(reel, i) / "scene.mp4", _narration(paths.edit_dir(reel, i))) for i in ids_],
                   cd, fade_out=cut != "gif")
            stamp.write(cd, cs)
        cut_stamps[cut], masters[cut] = cs, cd / "master.mp4"
        info = json.loads((cd / "cut.json").read_text())
        lines.append(f"{cut} {info['seconds']:.1f} s ({len(ids_)} segment{'s' if len(ids_) > 1 else ''})")
    _say("join       " + " · ".join(lines))

    data = paths.data_dir(reel)
    report_path = data / "report.json"
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    made = export(masters, data)
    for m in made.values():
        m["cut_stamp"] = cut_stamps[m["cut"]]
    tries = made["gif"]["tries"]
    _say(f"export     share.mp4 · readme.mp4 · GIF ({tries[-1]['width']} px, {tries[-1]['fps']} fps"
         + (f"; {tries[0]['width']} px was {tries[0]['bytes'] / 2**20:.1f} MB" if len(tries) > 1 else "") + ")")
    narrated = any(json.loads((paths.cut_dir(reel, c) / "cut.json").read_text())["narrated"] for c in ("share", "readme"))
    results = check(made, masters["gif"], cut_stamps, narrated, data / "leaks")
    ok = all(r["ok"] for r in results)
    report = {"deliverables": [], "checks": results}
    if previous.get("gif_written"):
        report["gif_written"] = previous["gif_written"]
    gif_line = "(not written: checks failed)"
    if ok:
        try:
            gif_line = _place_gif(reel, Path(made["gif"]["path"]), report, previous)
        except Failed as f:
            _fail(f, done)
            return 1
    sheets = []
    for name, video in (("share", data / "share.mp4"), ("readme", data / "readme.mp4"), ("gif", masters["gif"])):
        png = data / f"sheet-{name}.png"
        sheets.append((png, _sheet(video, png)))
    for name, m in made.items():
        path = Path(m["path"])
        p = probe(path)
        report["deliverables"].append({"name": name if name != "gif" else f"{reel['name']}.gif",
                                       "path": gif_line if name == "gif" else str(path), "seconds": round(p["duration"], 1),
                                       "bytes": path.stat().st_size, "cut_stamp": m["cut_stamp"]})
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    _say("\nDELIVERABLES")
    for d in report["deliverables"]:
        _say(f"  {d['name']:<14}{d['seconds']:>6.1f} s {d['bytes'] / 2**20:>6.1f} MB   {d['path']}")
    _say()
    print_report(results)
    _say("\nREVIEW  (look at these against the standards before delivering)")
    for png, what in sheets:
        _say(f"  {png}   {what}")
    _say("\n" + ("PASS" if ok else f"FAIL  deliverables written but not safe to publish; {paths.gif_path(reel)} left unchanged"))
    return 0 if ok else 1


def _fail(f: Failed, done: list) -> None:
    _say(f"\nFAIL {f.stage}" + (f"  scene={f.scene}" if f.scene else ""))
    for line in f.reason.splitlines():
        _say(f"  {line}")
    if f.todo:
        _say(f"  → {f.todo}")
    if done:
        _say(f"\nkept: {', '.join(done)} (recorded)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="reel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("make")
    s.add_argument("reel")
    s.add_argument("--rerecord", action="store_true")
    s = sub.add_parser("narrate")
    s.add_argument("reel")
    s.add_argument("--cut", choices=("share", "readme"), default="share")
    s.add_argument("--camera", default="0")
    s.add_argument("--mic", default="0")
    a = p.parse_args(argv)
    if a.cmd == "make":
        return make(a.reel, a.rerecord)
    from .narrate import narrate
    narrate(spec_mod.load(a.reel), a.cut, a.camera, a.mic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
