r"""Records a terminal demo with VHS inside tmux, logging when each step starts.

Spec fields for kind = "terminal":

    [terminal]
    workdir = "/tmp/aq-demo"  # where the demo runs (default /tmp/reel-<title>); shown in paths on screen
    setup = "setup.sh"        # run once before recording as: bash setup.sh <workdir>
    teardown = "teardown.sh"  # run after recording, even if it failed: bash teardown.sh <workdir>
    init = "cd $REEL_WORK"    # run in every pane before recording (not shown)
    font_size = 30            # 36-40 for one pane, so README-sized frames stay readable
    typing_ms = 45            # per character; long commands cost len x this on screen
    theme = "Catppuccin Mocha"
    prompt = "$ "

    [[pane]]                  # one or more; laid out in a grid, row by row
    name = "agent A"
    run = "aq status --top"   # optional: started before recording, not typed on screen
    noisy = true              # optional: keeps changing (a dashboard); not counted as activity

    [[step]]
    pane = "agent A"          # where to type (default: the first pane)
    type = "aq run -- ./build.sh"
    enter = true
    wait = "ok"               # optional: regex that must appear anywhere on screen (earlier output
                              # counts too: for a second "ok" write 'ok[\s\S]*ok') ...
    timeout = 30              # ... within this many seconds, else the recording fails
    allow_fail = false        # a typed command exiting non-zero fails the recording
    focus = "agent A"         # pane name(s) to frame, "full", or omit to follow the change
    hold = 1.0
    caption = "..."

How timing works: before each step the tape presses a tmux key that runs mark.sh, which
appends the wall-clock time to events.log; the shells in the panes log when each command
starts and ends. The first mark is taken just before recording starts and the last just
before it stops; video time is mapped linearly between them.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

W, H = 2880, 1620
MARGIN, PADDING, BAR = 80, 24, 60
FPS = 15
TYPING_MS = 45
SHOW_DELAY = 0.3   # tape: Sleep between the first mark and Show


class RecordError(RuntimeError):
    pass


def _bash() -> str:
    for c in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash"):
        if Path(c).exists():
            return c
    raise RecordError("needs bash 5 or newer for $EPOCHREALTIME: brew install bash")


def _need(tool: str):
    if not shutil.which(tool):
        raise RecordError(f"needs {tool} on PATH")


def _vhs_string(s: str) -> str:
    if '"' not in s:
        return f'"{s}"'
    if "`" not in s:
        return f"`{s}`"
    raise RecordError(f"cannot type text with both \" and `: {s!r}")


def _gradient(path: Path, colors: list, w: int, h: int):
    c0, c1 = (c.replace("#", "0x") for c in colors[:2])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"gradients=s={w}x{h}:c0={c0}:c1={c1}:x0=0:y0=0:x1={w}:y1={h}:nb_colors=2",
                    "-frames:v", "1", str(path)], check=True)


def record(spec: dict, out: Path) -> Path:
    """Records stage.mp4 and events.json into out; returns the events path."""
    for t in ("vhs", "tmux", "ffmpeg"):
        _need(t)
    bash = _bash()
    term = spec.get("terminal", {})
    panes = spec.get("pane") or [{"name": "main"}]
    names = [p["name"] for p in panes]
    steps = spec["step"]
    for i, s in enumerate(steps, 1):
        for key in ("pane",):
            if key in s and s[key] not in names:
                raise RecordError(f"step {i}: no pane named {s[key]!r}")

    out = Path(out).resolve()
    # The demo runs in a neutral directory: paths printed on screen must not show your home folder.
    work = Path(term.get("workdir", f"/tmp/reel-{_slug(spec['title'])}"))
    if not str(work.resolve()).startswith(("/tmp/", "/private/tmp/")):
        raise RecordError(f"workdir must be under /tmp, since it is wiped before each recording: {work}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    sock = f"reel{os.getpid()}"
    env = {**os.environ, "REEL_WORK": str(work), "LANG": os.environ.get("LANG", "en_US.UTF-8"),
           "BASH_SILENCE_DEPRECATION_WARNING": "1"}

    if term.get("setup"):
        setup = Path(spec["_dir"]) / term["setup"]
        subprocess.run([bash, str(setup), str(work)], check=True, env=env, cwd=spec["_dir"])
    work.mkdir(parents=True, exist_ok=True)
    log = work / "events.log"
    log.write_text("")

    _gradient(work / "bg.png", spec["accent"], W, H)

    # Every pane's shell logs command start/end with the pane name and exit code.
    prompt = term.get("prompt", "$ ")
    rc = work / "reelrc"
    rc.write_text(f"""
export BASH_SILENCE_DEPRECATION_WARNING=1 REEL_WORK={shlex.quote(str(work))}
{term.get("init", "")}
PS1={shlex.quote(prompt)}
__reel_log() {{ printf '%s %s %s %s\\n' "$EPOCHREALTIME" "$1" "$REEL_PANE" "$2" >> {shlex.quote(str(log))}; }}
__reel_armed=0
__reel_pre() {{ [[ $__reel_armed == 1 ]] || return; __reel_armed=0; __reel_log start "$(printf %q "$BASH_COMMAND")"; }}
__reel_post() {{ local s=$?; [[ $__reel_started == 1 ]] && __reel_log end "$s"; __reel_started=1; __reel_armed=1; }}
__reel_started=0
trap '__reel_pre' DEBUG
PROMPT_COMMAND=__reel_post
clear
""")
    mark = work / "mark.sh"
    mark.write_text(f"""#!{bash}
printf '%s mark - -\\n' "$EPOCHREALTIME" >> {shlex.quote(str(log))}
if [[ ! -f {shlex.quote(str(work / "geometry"))} ]]; then
  tmux -L {sock} display -p '#{{window_width}} #{{window_height}}' > {shlex.quote(str(work / "geometry"))}
  tmux -L {sock} list-panes -F '#{{pane_index}} #{{pane_left}} #{{pane_top}} #{{pane_width}} #{{pane_height}}' >> {shlex.quote(str(work / "geometry"))}
fi
""")
    mark.chmod(0o755)

    def tmux(*args):
        subprocess.run(["tmux", "-u", "-f", "/dev/null", "-L", sock, *args], check=True, env=env)

    subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
    # Panes log their index (names may contain spaces); _events maps it back to the name.
    shell = lambda name: f"REEL_PANE={names.index(name)} {bash} --rcfile {shlex.quote(str(rc))} -i"
    tmux("new-session", "-d", "-s", "reel", "-x", "200", "-y", "50", shell(names[0]))
    tmux("set", "-g", "status", "off", ";", "set", "-g", "mouse", "off", ";",
         "set", "-g", "pane-active-border-style", "fg=colour39")
    if len(names) > 1:
        tmux("set", "-g", "pane-border-status", "top", ";", "set", "-g", "pane-border-format", " #{pane_title} ")
    for name in names[1:]:
        tmux("split-window", "-t", "reel", shell(name))
        tmux("select-layout", "-t", "reel", "tiled")
    ids = subprocess.run(["tmux", "-L", sock, "list-panes", "-t", "reel", "-F", "#{pane_id}"],
                         capture_output=True, text=True, check=True, env=env).stdout.split()
    for pid, p in zip(ids, panes):
        tmux("select-pane", "-t", pid, "-T", p["name"])
        if p.get("run"):
            tmux("send-keys", "-t", pid, f"clear; {p['run']}", "Enter")
    for i, pid in enumerate(ids, 1):
        tmux("bind", str(i), "select-pane", "-t", pid)
    tmux("bind", "M", "run-shell", str(mark))
    tmux("select-pane", "-t", ids[0])

    tape = _tape(spec, term, names, work, sock)
    (work / "demo.tape").write_text(tape)
    try:
        r = subprocess.run(["vhs", str(work / "demo.tape")], env=env, cwd=work,
                           capture_output=True, text=True)
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
        if term.get("teardown"):
            subprocess.run([bash, str(Path(spec["_dir"]) / term["teardown"]), str(work)], env=env, cwd=spec["_dir"])
    marks = [float(l.split()[0]) for l in log.read_text().splitlines() if " mark " in l]
    if r.returncode != 0:
        failed = max(0, len(marks) - 1)  # marks: 1 before Show, then one per started step
        detail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise RecordError(f"step {failed} failed: {steps[failed - 1].get('wait') and 'waited for ' + repr(steps[failed - 1]['wait']) + ': ' or ''}"
                          + " / ".join(detail))
    return _events(spec, panes, steps, work, out)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-") or "demo"


def _tape(spec, term, names, work, sock) -> str:
    font = term.get("font_size", 30)
    lines = [
        f'Output "{work}/stage.mp4"',
        "Require tmux",
        "Set Shell bash",
        f"Set FontSize {font}",
        f"Set Width {W}", f"Set Height {H}",
        f"Set Padding {PADDING}", f"Set Margin {MARGIN}",
        f'Set MarginFill "{work}/bg.png"',
        "Set WindowBar Colorful", f"Set WindowBarSize {BAR}", "Set BorderRadius 20",
        f'Set Theme "{term.get("theme", "Catppuccin Mocha")}"',
        f"Set TypingSpeed {term.get('typing_ms', TYPING_MS)}ms",
        f"Set Framerate {FPS}",
        "Set CursorBlink false",
        "Hide",
        f'Type "tmux -u -L {sock} attach -t reel" Enter',
        "Sleep 2s",
        "Ctrl+B", 'Type "M"',
        f"Sleep {SHOW_DELAY}s",
        "Show",
        "Sleep 1.5s",  # the whole layout first, then the camera moves in
    ]
    for i, s in enumerate(spec["step"], 1):
        lines += [f"# step {i}", "Ctrl+B", 'Type "M"']
        if "pane" in s or len(names) > 1 and "type" in s:
            idx = names.index(s.get("pane", names[0])) + 1
            lines += ["Ctrl+B", f'Type "{idx}"', "Sleep 0.2s"]
        if s.get("type"):
            lines.append(f"Type {_vhs_string(s['type'])}")
            if s.get("enter", True):
                lines += ["Sleep 0.2s", "Enter"]
        if s.get("wait"):
            rx = s["wait"].replace("/", "\\/")
            lines.append(f"Wait+Screen@{s.get('timeout', 30)}s /{rx}/")
        lines.append(f"Sleep {s.get('hold', 1.0)}s")
    lines += ["Ctrl+B", 'Type "M"', "Hide", "Sleep 0.5s"]
    return "\n".join(lines) + "\n"


def _probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _events(spec, panes, steps, work, out) -> Path:
    stage = work / "stage.mp4"
    final = out / "stage.mp4"
    if stage.exists():
        if stage.stat().st_size == 0:
            raise RecordError("VHS finished but wrote no video")
        shutil.copy(work / "events.log", out / "events.log")
        shutil.move(str(stage), final)
    elif not final.exists():
        raise RecordError("VHS finished but wrote no video")
    duration = _probe_duration(final)

    rows = [l.split(" ", 3) for l in (work / "events.log").read_text().splitlines()]
    marks = [float(r[0]) for r in rows if r[1] == "mark"]
    if len(marks) != len(steps) + 2:
        raise RecordError(f"expected {len(steps) + 2} step marks, got {len(marks)}")
    # mark 0 is SHOW_DELAY before the first frame; the last mark is right before the last frame.
    t0 = marks[0] + SHOW_DELAY
    scale = duration / max(marks[-1] - t0, 1e-3)
    vt = lambda wall: round(max(0.0, (wall - t0) * scale), 3)

    regions = _regions(panes, work)
    cmds, open_ = [], {}
    names = [p["name"] for p in panes]
    for r in rows:
        if r[1] in ("start", "end") and r[2].isdigit():
            r[2] = names[int(r[2])]
    for r in rows:
        if r[1] == "start":
            open_[r[2]] = {"pane": r[2], "start": vt(float(r[0])), "cmd": r[3] if len(r) > 3 else ""}
        elif r[1] == "end" and r[2] in open_:
            c = open_.pop(r[2])
            c.update(end=vt(float(r[0])), exit=int(r[3]))
            cmds.append(c)
    cmds += list(open_.values())

    noisy = [p["name"] for p in panes if p.get("noisy")]
    beats = []
    step_marks = marks[1:-1]
    for i, (s, m) in enumerate(zip(steps, step_marks)):
        start = vt(m)
        end = vt(step_marks[i + 1]) if i + 1 < len(step_marks) else duration
        focus = s.get("focus", s.get("pane") if s.get("type") else None)
        if isinstance(focus, str):
            focus = [focus]
        beats.append({"start": start, "end": round(end, 3), "label": f"step {i + 1}",
                      "focus": focus or [], "ignore": [n for n in noisy if n not in (focus or [])],
                      "caption": s.get("caption"), "pane": s.get("pane", panes[0]["name"]),
                      "typed": bool(s.get("type")), "allow_fail": bool(s.get("allow_fail"))})

    # A typed command that exits non-zero fails the recording (unless the step allows it).
    for i, b in enumerate(beats, 1):
        if not b["typed"] or b["allow_fail"]:
            continue
        mine = [c for c in cmds if c["pane"] == b["pane"] and b["start"] - 0.5 <= c["start"] <= b["end"] + 0.5]
        for c in mine:
            if c.get("exit", 0) != 0:
                raise RecordError(f"step {i}: `{c['cmd']}` exited with {c['exit']}")

    events = {
        "kind": "terminal",
        "stage": {"path": "stage.mp4", "width": W, "height": H, "duration": duration, "fps": FPS},
        "regions": regions,
        "beats": beats,
        "commands": cmds,
        "sync": {"marks": len(marks), "scale": round(scale, 4)},
    }
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    return path


def _regions(panes, work) -> dict:
    lines = (work / "geometry").read_text().split("\n")
    cols, rows = (int(v) for v in lines[0].split())
    x0, y0 = MARGIN + PADDING, MARGIN + BAR + PADDING
    cw = (W - 2 * (MARGIN + PADDING)) / cols
    ch = (H - y0 - MARGIN - PADDING) / rows
    regions = {"full": [0, 0, W, H]}
    titled = len(panes) > 1
    for line, p in zip(sorted((l for l in lines[1:] if l.strip()), key=lambda l: int(l.split()[0])), panes):
        _, left, top, width, height = (int(v) for v in line.split())
        top_px = y0 + (top - (1 if titled else 0)) * ch
        regions[p["name"]] = [round(x0 + left * cw, 1), round(top_px, 1),
                              round(x0 + (left + width) * cw, 1), round(y0 + (top + height) * ch, 1)]
    return regions
