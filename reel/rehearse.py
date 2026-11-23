"""Rehearsal: a terminal scene run once without recording, before `reel make` records it.

It runs the setup, the panes and every step the way the recording will (same rc, same panes, same order
and holds, device `find` commands polled), but types instantly and reads tmux's own screen, which stays
current where the recorder's terminal can stall. Afterwards it names every problem a recording would hit:
a typed command that exits non-zero, one that never finishes, a `wait` that never shows up, and sensitive
text anywhere in the panes' output (home paths, user name, tokens, private patterns). A rehearsal that
passed is reused while the spec's folder is unchanged (CASE-D2.2); set REEL_REHEARSE=always to run it
anyway, or `[terminal] rehearse = false` to skip it for a scene.

Recording a scene that fails takes minutes; a rehearsal takes the demo's own run time (2026-11-23
dogfood: 5 of 8 recording failures would have shown up here).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import check
from .record_terminal import RecordError, _DeviceRecorders, _bash, _slug, write_rc

POLL = 0.25


def fingerprint(spec_path: Path) -> str:
    """Hash of the spec's folder (spec, scripts, pages): a rehearsal stays valid while none of it changes."""
    h = hashlib.sha1()
    for f in sorted(Path(spec_path).resolve().parent.iterdir()):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def judge(steps: list, commands: list, missed: dict, leaks: list) -> list:
    """Problems a recording would hit (CASE-D2.1). commands: [{step, cmd, exit}] with exit None for a
    command that never finished; missed: {step: wait regex never seen}; leaks: [(kind, text)]."""
    problems = []
    for c in commands:
        s = steps[c["step"] - 1]
        if c["exit"] is None:
            problems.append(f"step {c['step']}: `{c['cmd']}` never finished (it hangs, or needs longer than its timeout)")
        elif c["exit"] != 0 and not s.get("allow_fail"):
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


def rehearse(spec: dict, out: Path) -> dict:
    """Runs the scene once without recording; returns the report, raises RecordError listing the problems."""
    term = spec.get("terminal", {})
    out = Path(out)
    fp = fingerprint(Path(spec["_path"]))
    prev = out / "rehearsal.json"
    if os.environ.get("REEL_REHEARSE") != "always" and prev.exists():
        old = json.loads(prev.read_text())
        if old.get("fingerprint") == fp and old.get("ok"):
            print("rehearsal: reused (nothing in the spec's folder changed since it passed)")
            return old
    bash = _bash()
    panes = spec.get("pane") or [{"name": "main"}]
    names = [p["name"] for p in panes]
    steps = spec["step"]
    work = Path(str(term.get("workdir", f"/tmp/reel-{_slug(spec['title'])}")) + "-rehearsal")
    if not str(work.resolve()).startswith(("/tmp/", "/private/tmp/")):
        raise RecordError(f"workdir must be under /tmp: {work}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = {**os.environ, "REEL_WORK": str(work), "BASH_SILENCE_DEPRECATION_WARNING": "1"}
    t0 = time.monotonic()
    if term.get("setup"):
        r = subprocess.run([bash, str(Path(spec["_dir"]) / term["setup"]), str(work)], env=env, cwd=spec["_dir"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            if term.get("teardown"):
                subprocess.run([bash, str(Path(spec["_dir"]) / term["teardown"]), str(work)], env=env, cwd=spec["_dir"])
            raise RecordError(f"rehearsal: setup {term['setup']} exited with {r.returncode}: "
                              f"{(r.stderr or r.stdout).strip()[-300:]}")
    log = work / "events.log"
    log.write_text("")
    rc = write_rc(work, term, log)
    sock = f"rehearse{os.getpid()}"
    shell = lambda name: f"REEL_PANE={names.index(name)} {bash} --rcfile {rc} -i"
    _tmux(sock, "kill-server")
    _tmux(sock, "new-session", "-d", "-s", "r", "-x", "160", "-y", "50", shell(names[0]), check_=True)
    for name in names[1:]:
        _tmux(sock, "split-window", "-t", "r", shell(name), check_=True)
        _tmux(sock, "select-layout", "-t", "r", term.get("layout", "tiled"))
    ids = _tmux(sock, "list-panes", "-t", "r", "-F", "#{pane_id}", check_=True).stdout.split()
    time.sleep(1.0)
    for pid, p in zip(ids, panes):
        if p.get("run"):
            _tmux(sock, "send-keys", "-t", pid, f"clear; {p['run']}", "Enter")
    time.sleep(0.5)
    base = len(log.read_text().splitlines())  # what the panes' own `run` commands logged is not a step's
    devices = _DeviceRecorders(spec.get("device", []), work, env, bash, record=False)
    devices.start()
    missed, typed_steps = {}, []
    try:
        for i, s in enumerate(steps, 1):
            pane = ids[names.index(s.get("pane", names[0]))]
            if s.get("type"):
                _tmux(sock, "send-keys", "-t", pane, "-l", s["type"])
                if s.get("enter", True):
                    _tmux(sock, "send-keys", "-t", pane, "Enter")
                typed_steps.append(i)
            if s.get("wait"):
                rx = re.compile(s["wait"])
                deadline = time.monotonic() + float(s.get("timeout", 30))
                while not rx.search(_screen(sock, ids)):
                    if time.monotonic() > deadline:
                        missed[i] = s["wait"]
                        break
                    time.sleep(POLL)
            time.sleep(min(float(s.get("hold", 1.0)), 2.0))
        time.sleep(0.5)
        screens = _screen(sock, ids, history=True)
    finally:
        devices.stop()
        _tmux(sock, "kill-server")
        td = None
        if term.get("teardown"):
            td = subprocess.run([bash, str(Path(spec["_dir"]) / term["teardown"]), str(work)], env=env,
                                cwd=spec["_dir"], capture_output=True, text=True)
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
    if td is not None and td.returncode != 0:
        problems.append(f"teardown failed: {(td.stderr or td.stdout).strip()[-300:]}")
    report = {"fingerprint": fp, "ok": not problems, "problems": problems, "commands": cmds,
              "seconds": round(time.monotonic() - t0, 1)}
    out.mkdir(parents=True, exist_ok=True)
    prev.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    timing = ", ".join(f"step {c['step']} {c['seconds']} s" for c in cmds if c["seconds"] is not None)
    if problems:
        raise RecordError("rehearsal found problems before recording:\n  " + "\n  ".join(problems))
    print(f"rehearsal: ok in {report['seconds']} s ({timing})")
    return report
