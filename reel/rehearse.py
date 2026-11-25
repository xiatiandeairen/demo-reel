"""Rehearsal: a terminal scene run once without recording, before `reel make` records it.

It runs the panes and every step the way the take will (same rc, same panes and size, same order and holds,
device `find` commands polled), in the workdir the agent prepared (the scene's reset runs first), but
types instantly and reads tmux's own screen, which stays current where the recorder's terminal can stall.
Afterwards it names every problem a take would hit: a typed command that exits non-zero, one that never
finishes, a `wait` that never shows up, and sensitive text in the panes' output (home paths, user name,
tokens, private patterns). It also measures how long each step took: the take's timeouts follow from that.
A rehearsal that passed is reused while the take's inputs are unchanged (reel/stamp.py).

Recording a scene that fails takes minutes; a rehearsal takes the demo's own run time (2026-11-23
dogfood: 5 of 8 recording failures would have shown up here).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import check
from .record_terminal import COLS, ROWS, RecordError, _DeviceRecorders, _bash, workdir, write_rc

POLL = 0.25
WAIT_LIMIT = 900   # seconds a rehearsal waits for one step (a cold Xcode build takes minutes)
TIMEOUT_FACTOR, TIMEOUT_PAD, TIMEOUT_MIN = 3.0, 10.0, 30.0


def timeout(seconds: float | None) -> float:
    """A take's timeout for a step that took `seconds` in the rehearsal: a recording machine is busier."""
    return round(max(TIMEOUT_MIN, (seconds or 0.0) * TIMEOUT_FACTOR + TIMEOUT_PAD), 1)


def judge(steps: list, commands: list, missed: dict, leaks: list) -> list:
    """Problems a recording would hit (CASE-D2.1). commands: [{step, cmd, exit}] with exit None for a
    command that never finished; missed: {step: wait regex never seen}; leaks: [(kind, text)]."""
    problems = []
    for c in commands:
        s = steps[c["step"] - 1]
        if c["exit"] is None:
            problems.append(f"step {c['step']}: `{c['cmd']}` never finished (it hangs, or needs longer than its timeout)")
        elif c["exit"] != 0:
            problems.append(f"step {c['step']}: `{c['cmd']}` exited with {c['exit']}")
    for k, rx in sorted(missed.items()):
        problems.append(f"step {k}: waited for {rx!r}, never on screen")
    for kind, text in leaks:
        problems.append(f"sensitive text on screen: {kind} {text!r}")
    return problems


def _tmux(sock, *args, check_=False):
    return subprocess.run(["tmux", "-u", "-f", "/dev/null", "-L", sock, *args], capture_output=True, text=True,
                          check=check_)


def _screen(sock, pane_ids, history=False) -> str:
    extra = ["-S", "-"] if history else []
    return "\n".join(_tmux(sock, "capture-pane", "-p", "-J", *extra, "-t", p).stdout for p in pane_ids)


def rehearse(spec: dict, scene_dir: Path, stamp: str) -> dict:
    """Runs the scene once without recording and writes scene_dir/rehearsal.json; reused while `stamp`
    (the take's inputs) is unchanged. Raises RecordError listing the problems."""
    term = spec.get("terminal", {})
    scene_dir = Path(scene_dir)
    prev = scene_dir / "rehearsal.json"
    if prev.exists():
        old = json.loads(prev.read_text())
        if old.get("stamp") == stamp and old.get("ok"):
            return {**old, "reused": True}
    bash = _bash()
    panes = spec["pane"]
    names = [p["name"] for p in panes]
    steps = spec["step"]
    work = workdir(spec)
    if not work.is_dir():
        raise RecordError(f"workdir {work} does not exist: the agent prepares it (or the scene's reset does)")
    scratch = scene_dir / "rehearse-tmp"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    env = {**os.environ, "REEL_WORK": str(work), "BASH_SILENCE_DEPRECATION_WARNING": "1"}
    t0 = time.monotonic()
    log = scratch / "events.log"
    log.write_text("")
    rc = write_rc(scratch, work, term, log)
    sock = f"rehearse{os.getpid()}"
    shell = lambda name: f"REEL_PANE={names.index(name)} {bash} --rcfile {rc} -i"
    _tmux(sock, "kill-server")
    _tmux(sock, "new-session", "-d", "-s", "r", "-c", str(work), "-x", str(COLS), "-y", str(ROWS), shell(names[0]),
          check_=True)
    for name in names[1:]:
        _tmux(sock, "split-window", "-t", "r", "-c", str(work), shell(name), check_=True)
        _tmux(sock, "select-layout", "-t", "r", term["layout"])
    ids = _tmux(sock, "list-panes", "-t", "r", "-F", "#{pane_id}", check_=True).stdout.split()
    time.sleep(1.0)
    for pid, p in zip(ids, panes):
        if p.get("run"):
            _tmux(sock, "send-keys", "-t", pid, f"clear; {p['run']}", "Enter")
    time.sleep(0.5)
    base = len(log.read_text().splitlines())  # what the panes' own `run` commands logged is not a step's
    devices = _DeviceRecorders(spec.get("device", []), scratch, env, bash, record=False)
    devices.start()
    missed, typed_steps, waited = {}, [], {}
    try:
        for i, s in enumerate(steps, 1):
            pane = ids[names.index(s.get("pane", names[0]))]
            started = time.monotonic()
            if s.get("type"):
                _tmux(sock, "send-keys", "-t", pane, "-l", s["type"])
                _tmux(sock, "send-keys", "-t", pane, "Enter")
                typed_steps.append(i)
            if s.get("wait"):
                rx = re.compile(s["wait"])
                deadline = started + WAIT_LIMIT
                while not rx.search(_screen(sock, ids)):
                    if time.monotonic() > deadline:
                        missed[i] = s["wait"]
                        break
                    time.sleep(POLL)
                waited[i] = round(time.monotonic() - started, 1)
            time.sleep(min(float(s.get("hold", 1.0)), 2.0))
        time.sleep(0.5)
        screens = _screen(sock, ids, history=True)
    finally:
        devices.stop()
        _tmux(sock, "kill-server")
    # Pair each typed step with the command its pane started next (in order), as the recording does.
    rows = [l.split(" ", 3) for l in log.read_text().splitlines()[base:]]
    started = [r for r in rows if r[1] == "start"]
    cmds, used = [], set()
    for i in typed_steps:
        pane_ix = str(names.index(steps[i - 1].get("pane", names[0])))
        k = next((j for j, r in enumerate(started) if j not in used and r[2] == pane_ix), None)
        if k is None:
            cmds.append({"step": i, "cmd": steps[i - 1]["type"], "exit": None, "seconds": None})
            continue
        used.add(k)
        st = started[k]
        after = rows[rows.index(st) + 1:]
        end = next((r for r in after if r[1] == "end" and r[2] == pane_ix), None)
        cmds.append({"step": i, "cmd": steps[i - 1]["type"], "exit": int(end[3]) if end else None,
                     "seconds": round(float(end[0]) - float(st[0]), 1) if end else None})
    leaks = check.find_sensitive([l for l in screens.splitlines() if l.strip()], check.patterns(spec))
    leaks = list(dict.fromkeys(leaks))
    problems = judge(steps, cmds, missed, leaks)
    report = {"stamp": stamp, "ok": not problems, "problems": problems, "commands": cmds,
              "seconds": [waited.get(i) for i in range(1, len(steps) + 1)],
              "total": round(time.monotonic() - t0, 1)}
    prev.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    shutil.rmtree(scratch, ignore_errors=True)
    if problems:
        raise RecordError("rehearsal found problems before recording:\n  " + "\n  ".join(problems))
    return report
