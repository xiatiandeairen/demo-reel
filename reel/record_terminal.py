r"""Records a terminal demo with VHS inside tmux, logging when each step starts.

Spec fields for kind = "terminal":

    [terminal]
    workdir = "/tmp/aq-demo"  # where the demo runs (default /tmp/reel-<title>); shown in paths on screen
    setup = "setup.sh"        # run once before recording as: bash setup.sh <workdir>
    teardown = "teardown.sh"  # run after recording, even if it failed: bash teardown.sh <workdir>
    init = "cd $REEL_WORK"    # run in every pane before recording (not shown)
    font_size = 40            # 48-54 for one pane, so README-sized frames stay readable
    open_hold = 1.5           # seconds on the whole layout before the first step (0.6 for a film's later scene)
    keep_files = ["app/runs.log"]  # files (relative to workdir) copied into this scene's state as files/...;
                              # a card reads them as {files:<this scene>.toml}/app/runs.log
    typing_ms = 45            # per character; long commands cost len x this on screen
    theme = "Catppuccin Mocha"
    prompt = "$ "
    layout = "tiled"          # tmux layout: tiled (grid) or even-vertical (stacked rows)
    rehearse = true           # run the scene once unrecorded before recording (reel/rehearse.py)

    [[pane]]                  # one or more; laid out in a grid, row by row
    name = "agent A"
    run = "aq status --top"   # optional: started before recording, not typed on screen
    noisy = true              # optional: keeps changing (a dashboard); not counted as activity

    [[device]]                # optional: an iOS simulator shown beside the terminal, right of it
    name = "A's simulator"    # label under the phone; also a focus name
    find = "cat $REEL_WORK/sim"   # shell command polled every 0.5 s until it prints the simulator's
                              # UDID; recording of that simulator starts then (a placeholder before)

    [[step]]
    pane = "agent A"          # where to type (default: the first pane)
    type = "aq run -- ./build.sh"
    enter = true
    wait = "ok"               # optional: regex that must appear anywhere on screen (earlier output
                              # counts too: for a second "ok" write 'ok[\s\S]*ok') ...
    timeout = 30              # ... within this many seconds, else the recording fails
    allow_fail = false        # a typed command exiting non-zero fails the recording
    keep_time = false         # play this command's whole run uncut, for comparing durations
    timer = "xcodebuild"      # draw a timer bar with this label over the command's run (implies keep_time);
                              # every bar uses the spec's top-level timer_scale (seconds for a full bar, 10)
    squeeze = false           # cut the middle of this command's run even while the screen moves (a page
                              # loading, a clone): keeps 0.5 s after the start, 1.5 s before the end, and the narration
    focus = "agent A"         # pane name(s) to frame, "full", or omit to follow the change
    hold = 1.0
    caption = "..."

How timing works: before each step the tape presses a tmux key that runs mark.sh, which
appends the wall-clock time to events.log; the shells in the panes log when each command
starts and ends. The first mark is taken just before recording starts and the last just
before it stops; video time is mapped linearly between them.

Devices are recorded apart from the terminal, with `xcrun simctl io <udid> recordVideo` (no window
needed), from the moment "Recording started" is printed. That wall-clock time, minus the stage's
own start, places each phone's video on the stage (device_placement).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

W, H = 3840, 2160  # 2x the output, so a 3x zoom is only a 1.5x upscale
COLS, ROWS = 200, 50  # tmux size, the same for the rehearsal and the take so lines wrap alike
PROMPT = "$ "
MARGIN, PADDING, BAR = 107, 32, 80
FPS = 15
TYPING_MS = 45
SHOW_DELAY = 0.3   # tape: Sleep between the first mark and Show
MARK_OFF, MARK_ON, MARK_GLYPH = 235, 238, "█"  # xterm greys #262626 / #444444: barely visible, easy to detect
RETIME_FPS = 30
PHONE_ASPECT = 1206 / 2622   # iPhone 17 Pro screen, as recordVideo writes it
DEVICE_GAP, DEVICE_LABEL = 80, 120
CAPTION_BAND = round(H * 0.17)  # the bottom of the stage, where captions sit at zoom 1
UDID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def device_rects(n: int) -> tuple:
    """(terminal width, [phone screen rect]) for n phones in a column band on the right of the stage.
    Each phone's label sits above it, and the phones end above CAPTION_BAND, so a caption never covers a
    label or the bottom of a screen (defect c, 2026-11-24 review)."""
    if not n:
        return W, []
    top = MARGIN + DEVICE_LABEL
    sh = H - CAPTION_BAND - top
    sw = round(sh * PHONE_ASPECT)
    band = n * sw + (n + 1) * DEVICE_GAP
    term_w = W - band + DEVICE_GAP  # the terminal's own right margin is the first gap
    rects = [[term_w + k * (sw + DEVICE_GAP), top, term_w + k * (sw + DEVICE_GAP) + sw, top + sh] for k in range(n)]
    return term_w, rects


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

    devices = spec.get("device", [])
    if devices and shutil.which("xcrun") is None:
        raise RecordError("devices need Xcode's xcrun")
    term_w, _ = device_rects(len(devices))
    out = Path(out).resolve()
    # The demo runs where the agent prepared it; reel's own files go to a scratch folder in the scene's
    # state, so nothing of reel's shows up when the demo lists its directory.
    work = workdir(spec)
    if not work.is_dir():
        raise RecordError(f"workdir {work} does not exist: the agent prepares it (or the scene's reset does)")
    scratch = out.parent / "tmp"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    sock = f"reel{os.getpid()}"
    env = {**os.environ, "REEL_WORK": str(work), "LANG": os.environ.get("LANG", "en_US.UTF-8"),
           "BASH_SILENCE_DEPRECATION_WARNING": "1"}
    log = scratch / "events.log"
    log.write_text("")

    from . import cards
    cards.background(scratch / "bg.png", spec["accent"], W, H)
    if devices:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(scratch / "bg.png"), "-vf",
                        f"crop={term_w}:{H}:0:0", str(scratch / "bg-term.png")], check=True)

    rc = write_rc(scratch, work, term, log)
    mark = scratch / "mark.sh"
    mark.write_text(f"""#!{bash}
printf '%s mark - -\\n' "$EPOCHREALTIME" >> {shlex.quote(str(log))}
n=$(grep -c ' mark ' {shlex.quote(str(log))})
tmux -L {sock} set -g status-right "#[fg=colour$(( n % 2 ? {MARK_ON} : {MARK_OFF} ))]{MARK_GLYPH}"
# tmux only redraws the status line on its own schedule; draw it now, or the flip shows up late.
for c in $(tmux -L {sock} list-clients -F '#{{client_name}}'); do tmux -L {sock} refresh-client -S -t "$c"; done
if [[ ! -f {shlex.quote(str(scratch / "geometry"))} ]]; then
  tmux -L {sock} display -p '#{{window_width}} #{{window_height}}' > {shlex.quote(str(scratch / "geometry"))}
  tmux -L {sock} list-panes -F '#{{pane_index}} #{{pane_left}} #{{pane_top}} #{{pane_width}} #{{pane_height}}' >> {shlex.quote(str(scratch / "geometry"))}
fi
""")
    mark.chmod(0o755)

    def tmux(*args):
        subprocess.run(["tmux", "-u", "-f", "/dev/null", "-L", sock, *args], check=True, env=env)

    subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
    # Panes log their index (names may contain spaces); _events maps it back to the name.
    shell = lambda name: f"REEL_PANE={names.index(name)} {bash} --rcfile {shlex.quote(str(rc))} -i"
    tmux("new-session", "-d", "-s", "reel", "-c", str(work), "-x", str(COLS), "-y", str(ROWS), shell(names[0]))
    # The status line carries only the step marker (bottom right): a cell that flips between two dark
    # greys at each step, so the video itself says when each step started (see _mark_times).
    tmux("set", "-g", "status", "on", ";", "set", "-g", "status-style", "bg=default", ";",
         "set", "-g", "status-left", "", ";", "set", "-g", "window-status-format", "", ";",
         "set", "-g", "window-status-current-format", "", ";",
         "set", "-g", "status-right", f"#[fg=colour{MARK_OFF}]{MARK_GLYPH}", ";", "set", "-g", "mouse", "off", ";",
         "set", "-g", "pane-active-border-style", "fg=colour39")
    if len(names) > 1:
        tmux("set", "-g", "pane-border-status", "top", ";", "set", "-g", "pane-border-format", " #{pane_title} ")
    for name in names[1:]:
        tmux("split-window", "-t", "reel", "-c", str(work), shell(name))
        tmux("select-layout", "-t", "reel", term["layout"])
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

    tape = _tape(spec, term, names, scratch, sock, term_w)
    (scratch / "demo.tape").write_text(tape)
    recorders = _DeviceRecorders(devices, scratch, env, bash)
    try:
        recorders.start()
        r = subprocess.run(["vhs", str(scratch / "demo.tape")], env=env, cwd=scratch,
                           capture_output=True, text=True)
    finally:
        recorders.stop()
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
    marks = [float(l.split()[0]) for l in log.read_text().splitlines() if " mark " in l]
    if r.returncode == 0 and term.get("keep_files"):
        keep_files(work, out, term["keep_files"])
    if r.returncode != 0:
        failed = max(0, len(marks) - 1)  # marks: 1 before Show, then one per started step
        detail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise RecordError(f"step {failed} failed: {steps[failed - 1].get('wait') and 'waited for ' + repr(steps[failed - 1]['wait']) + ': ' or ''}"
                          + " / ".join(detail))
    path = _events(spec, panes, steps, scratch, out, recorders.takes, term_w)
    shutil.rmtree(scratch, ignore_errors=True)
    return path


class _DeviceRecorders:
    """Finds each device's UDID while the demo runs and records its screen from then on."""

    def __init__(self, devices, work, env, bash, record=True):
        self.devices, self.work, self.env, self.bash, self.record = devices, work, env, bash, record
        self.takes = [None] * len(devices)  # {"path", "started", "udid"} once recording
        self.procs, self.done = [], threading.Event()
        self.threads = [threading.Thread(target=self._run, args=(k,), daemon=True) for k in range(len(devices))]

    def start(self):
        for t in self.threads:
            t.start()

    def _run(self, k):
        d = self.devices[k]
        while not self.done.is_set():
            r = subprocess.run([self.bash, "-c", d["find"]], capture_output=True, text=True, env=self.env)
            udid = r.stdout.strip().splitlines()[-1].strip() if r.stdout.strip() else ""
            if UDID.match(udid):
                break
            time.sleep(0.5)
        else:
            return
        if not self.record:  # rehearsal: the find command ran (it may prepare the device); nothing to film
            self.takes[k] = {"udid": udid}
            return
        path = self.work / f"device{k}.mp4"
        p = subprocess.Popen(["xcrun", "simctl", "io", udid, "recordVideo", "--codec=h264", "--force", str(path)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        for line in p.stdout:
            if "Recording started" in line:
                self.takes[k] = {"path": str(path), "started": time.time(), "udid": udid}
                break
        threading.Thread(target=p.stdout.read, daemon=True).start()  # drain the rest

    def stop(self):
        self.done.set()
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in self.procs:
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()


def keep_files(work: Path, out: Path, names: list) -> None:
    """Copies files the demo wrote (paths relative to the workdir) into <state>/files, where they survive
    the next recording and a reboot; a results card reads them there (CASE-D3.1)."""
    for name in names:
        src = Path(work) / name
        if not src.exists():
            raise RecordError(f"keep_files: {name} was not written in {work}")
        dst = Path(out) / "files" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


def beat_focus(step: dict, panes: list) -> list:
    """What a step's camera frames: its focus, else the pane it types in, else [] (the planner decides)."""
    focus = step.get("focus", step.get("pane", panes[0]["name"]) if step.get("type") else None)
    return [focus] if isinstance(focus, str) else list(focus or [])


def workdir(spec: dict) -> Path:
    """Where a terminal scene's demo runs: [terminal] workdir, prepared by the agent (or the scene's reset)."""
    return Path(spec.get("terminal", {}).get("workdir", f"/tmp/reel-{_slug(spec['id'])}"))


def write_rc(scratch: Path, work: Path, term: dict, log: Path) -> Path:
    """The rc file every pane's shell starts from: the spec's init, the prompt, and a log line per command
    start and end with the pane's index and exit code (used by recording and by rehearsal)."""
    prompt = PROMPT
    rc = scratch / "reelrc"
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
    return rc


def device_placement(started_wall: float, t0: float) -> tuple:
    """(delay, trim) in seconds for a device recording that started at wall time started_wall, on a
    stage whose time 0 is wall time t0: start it later, or cut its head if it began first (CASE-C3.2)."""
    d = round(started_wall - t0, 3)
    return (d, 0.0) if d >= 0 else (0.0, -d)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-") or "demo"


def _tape(spec, term, names, work, sock, term_w=W) -> str:
    """The VHS tape; work is reel's scratch folder (the video and backgrounds go there)."""
    font = term["font_size"]
    lines = [
        f'Output "{work}/stage.mp4"',
        "Require tmux",
        "Set Shell bash",
        f"Set FontSize {font}",
        f"Set Width {term_w}", f"Set Height {H}",
        f"Set Padding {PADDING}", f"Set Margin {MARGIN}",
        f'Set MarginFill "{work}/{"bg.png" if term_w == W else "bg-term.png"}"',
        "Set WindowBar Colorful", f"Set WindowBarSize {BAR}", "Set BorderRadius 20",
        'Set Theme "Catppuccin Mocha"',
        f"Set TypingSpeed {TYPING_MS}ms",
        f"Set Framerate {FPS}",
        "Set CursorBlink false",
        "Hide",
        f'Type "tmux -u -L {sock} attach -t reel" Enter',
        "Sleep 2s",
        "Ctrl+B", 'Type "M"',
        f"Sleep {SHOW_DELAY}s",
        "Show",
        f"Sleep {float(term.get('open_hold', 1.5))}s",  # the whole layout first, then the camera moves in
    ]
    for i, s in enumerate(spec["step"], 1):
        lines += [f"# step {i}", "Ctrl+B", 'Type "M"']
        if "pane" in s or len(names) > 1 and "type" in s:
            idx = names.index(s.get("pane", names[0])) + 1
            lines += ["Ctrl+B", f'Type "{idx}"', "Sleep 0.2s"]
        if s.get("type"):
            lines.append(f"Type {_vhs_string(s['type'])}")
            lines += ["Sleep 0.2s", "Enter"]
        if s.get("wait"):
            rx = s["wait"].replace("/", "\\/")
            lines.append(f"Wait+Screen@{s.get('_timeout', 30)}s /{rx}/")
        # Hold at least until the step's narration has been spoken (CASE-B7.1); typing already took some.
        typed = len(s.get("type", "")) * TYPING_MS / 1000 + (0.4 if s.get("type") else 0)
        hold = max(float(s.get("hold", 1.0)), s.get("_narration", 0.0) + 0.3 - typed)
        lines.append(f"Sleep {hold:.2f}s")
    # Stay visible a moment after the end mark, so its flip is in the video and the last stretch is
    # timed from it rather than extrapolated (which came out seconds short on a busy machine).
    lines += ["Ctrl+B", 'Type "M"', "Sleep 0.6s", "Hide", "Sleep 0.5s"]
    return "\n".join(lines) + "\n"


def _probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _events(spec, panes, steps, work, out, takes=(), term_w=W) -> Path:
    stage = work / "stage.mp4"
    final = out / "stage.mp4"
    if stage.exists():
        if stage.stat().st_size == 0:
            raise RecordError("VHS finished but wrote no video")
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
    regions = _regions(panes, work, term_w)
    # VHS drops frames when it cannot capture in time (about 20% at 4K, unevenly: worst while the
    # machine is busy), so the video runs faster than reality. The marker cell tells when each step
    # mark shows up in the video; the video is stretched back to wall-clock time piece by piece, so
    # typing looks real and narration, which plays in real time, fits its step.
    flips = _mark_times(final, regions["_marker"])
    # The first mark is set while the recording is hidden, so its flip (if seen) lands on the first
    # frames, not at its time; pair the step marks (and the end mark, if seen) from their flips.
    if len(flips) == len(marks):
        flips = flips[1:]
    pairs = [(v, w - t0) for v, w in zip(flips, marks[1:])]
    method = "marks" if len(flips) >= len(steps) else "uniform"
    if method == "uniform":
        scale = duration / max(marks[-1] - t0, 1e-3)
        pairs = [(0.0, 0.0), (duration, duration / scale)]
    dropped = round(1 - duration / max(marks[-1] - t0, 1e-3), 3)
    _retime(final, pairs, duration, work)
    duration = _probe_duration(final)
    devices = spec.get("device", [])
    raw_takes = []
    if devices:
        # Keep the sources: the terminal alone and each phone's own recording, so the composite can be
        # rebuilt by `reel plan` without recording again (composite_devices).
        shutil.copy(final, out / "stage-term.mp4")
        (out / "devices").mkdir(exist_ok=True)
        for k, (d, take) in enumerate(zip(devices, takes)):
            row = {"name": d["name"], "recorded": bool(take and Path(take["path"]).exists())}
            if row["recorded"]:
                shutil.copy(take["path"], out / "devices" / f"device{k}.mp4")
                row.update(path=f"devices/device{k}.mp4", started=take["started"], udid=take["udid"])
            raw_takes.append(row)
        missing = [r["name"] for r in raw_takes if not r["recorded"]]
        if missing:
            raise RecordError(f"no recording of {', '.join(missing)}: its find command never printed a UDID")
        for d, rect in zip(devices, device_rects(len(devices))[1]):
            regions[d["name"]] = rect
    vt = lambda wall: round(min(max(0.0, wall - t0), duration), 3)
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
        focus = beat_focus(s, panes)
        beats.append({"start": start, "end": round(end, 3), "label": f"step {i + 1}",
                      "focus": focus or [], "ignore": [n for n in noisy if n not in (focus or [])],
                      "pane": s.get("pane", panes[0]["name"]),
                      "full": focus == [] or focus == ["full"], "narration": s.get("_narration", 0.0)})

    # A typed command that exits non-zero fails the recording.
    for i, (s, b) in enumerate(zip(steps, beats), 1):
        if not s.get("type"):
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
        "sync": {"marks": len(marks), "method": method, "marks_seen": len(flips), "frames_dropped": dropped},
    }
    if raw_takes:
        events["devices"] = raw_takes
        events["device_sync"] = {"t0": t0, "term_width": term_w}
    path = out / "events.json"
    path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n")
    if raw_takes:
        composite_devices(out, spec["accent"])
    return path


def _regions(panes, work, term_w=W) -> dict:
    lines = (work / "geometry").read_text().split("\n")
    cols, rows = (int(v) for v in lines[0].split())
    x0, y0 = MARGIN + PADDING, MARGIN + BAR + PADDING
    cw = (term_w - 2 * (MARGIN + PADDING)) / cols
    ch = (H - y0 - MARGIN - PADDING) / (rows + 1)  # + the status line
    regions = {"full": [0, 0, W, H],
               "_marker": [round(x0 + (cols - 1) * cw, 1), round(y0 + rows * ch, 1),
                           round(x0 + cols * cw, 1), round(y0 + (rows + 1) * ch, 1)]}
    titled = len(panes) > 1
    for line, p in zip(sorted((l for l in lines[1:] if l.strip()), key=lambda l: int(l.split()[0])), panes):
        _, left, top, width, height = (int(v) for v in line.split())
        top_px = y0 + (top - (1 if titled else 0)) * ch
        regions[p["name"]] = [round(x0 + left * cw, 1), round(top_px, 1),
                              round(x0 + (left + width) * cw, 1), round(y0 + (top + height) * ch, 1)]
    return regions


def composite_devices(out: Path, accent) -> list:
    """stage.mp4 from stage-term.mp4 and each phone's recording in devices/: the stage widened to W with
    the phones in a band on the right, each placed by wall-clock time (device_placement). Run at the end
    of recording and again by `reel plan`, so changing how phones are laid in needs no new recording."""
    from . import cards
    out = Path(out)
    ev = json.loads((out / "events.json").read_text())
    takes, t0 = ev["devices"], ev["device_sync"]["t0"]
    term = out / "stage-term.mp4"
    duration = _probe_duration(term)
    _, rects = device_rects(len(takes))
    work = out / "devices"
    bg, frame, mask = work / "bg.png", work / "frames.png", work / "screen-mask.png"
    cards.background(bg, accent, W, H)
    cards.device_frames(frame, [t["name"] for t in takes], rects, W, H)
    sw, sh = rects[0][2] - rects[0][0], rects[0][3] - rects[0][1]
    cards.rounded_mask(mask, sw, sh, round(sw * 0.12))
    still = lambda p: ["-loop", "1", "-framerate", str(RETIME_FPS), "-t", f"{duration:.3f}", "-i", str(p)]
    inputs = [*still(bg), "-i", str(term), *still(frame), *still(mask)]
    g = ["[0:v][1:v]overlay=0:0:shortest=1[s0]", "[s0][2:v]overlay=0:0[s1]",
         f"[3:v]format=gray,split={len(takes)}" + "".join(f"[m{k}]" for k in range(len(takes)))]
    last, n, placed = "s1", 4, []
    for k, (take, rect) in enumerate(zip(takes, rects)):
        delay, trim = device_placement(take["started"], t0)
        inputs += ["-i", str(out / take["path"])]
        # recordVideo writes a frame only when the screen changes: make it constant-rate first, or
        # trimming a still opening would pull every later frame early.
        g.append(f"[{n}:v]fps={RETIME_FPS},trim=start={trim:.3f},setpts=PTS-STARTPTS+{delay:.3f}/TB,"
                 f"scale={sw}:{sh}:flags=lanczos,format=yuva420p[d{k}]")
        g.append(f"[d{k}][m{k}]alphamerge[r{k}]")
        g.append(f"[{last}][r{k}]overlay={rect[0]}:{rect[1]}:eof_action=repeat[o{k}]")
        last, n = f"o{k}", n + 1
        placed.append({"name": take["name"], "delay": delay, "trim": trim})
    wide = out / "stage-wide.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(g), "-map", f"[{last}]",
                    "-t", f"{duration:.3f}", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
                    "-pix_fmt", "yuv420p", str(wide)], check=True)
    shutil.move(str(wide), out / "stage.mp4")
    return placed


def _mark_times(video: Path, cell) -> list:
    """Video times at which the marker cell flips (one flip per step mark)."""
    x0, y0, x1, y1 = (int(v) for v in cell)
    w, h = max(2, x1 - x0 - 4), max(2, y1 - y0 - 4)
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf",
                          f"crop={w}:{h}:{x0 + 2}:{y0 + 2},scale=1:1:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True)
    num, den = (int(v) for v in r.stdout.strip().split("/"))
    fps = num / den
    if not raw:
        return []
    lo, hi = min(raw), max(raw)
    if hi - lo < 8:  # never flipped (or not visible)
        return []
    mid = (lo + hi) / 2
    state = raw[0] > mid
    flips = []
    for i, v in enumerate(raw):
        if (v > mid) != state:
            state = v > mid
            flips.append(round(i / fps, 3))
    return flips


def _retime(video: Path, pairs: list, duration: float, work: Path) -> None:
    """Stretches video so that video time pairs[k][0] lands on wall time pairs[k][1] (piecewise linear)."""
    pts = sorted(pairs)
    if len(pts) < 2:
        return
    def seg(a, b):
        (v0, w0), (v1, w1) = a, b
        k = (w1 - w0) / max(v1 - v0, 1e-3)
        return f"({w0:.4f}+(T-{v0:.4f})*{k:.5f})"
    expr = seg(pts[-2], pts[-1])  # beyond the last pair: keep the last slope
    for a, b in reversed(list(zip(pts, pts[1:]))[:-1]):
        expr = f"if(lt(T,{b[0]:.4f}),{seg(a, b)},{expr})"
    first = pts[0]
    k0 = (pts[1][1] - pts[0][1]) / max(pts[1][0] - pts[0][0], 1e-3)
    expr = f"if(lt(T,{first[0]:.4f}),max(0,{first[1]:.4f}+(T-{first[0]:.4f})*{k0:.5f}),{expr})"
    retimed = work / "stage-retimed.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    f"setpts='({expr})/TB',fps={RETIME_FPS}", "-c:v", "libx264", "-crf", "16",
                    "-preset", "medium", "-pix_fmt", "yuv420p", str(retimed)], check=True)
    shutil.move(str(retimed), video)
