# demo-reel

English · [简体中文](README.zh-CN.md)

Turn a short script into a polished product demo for X and your README: real commands, a camera that follows the action, long waits cut, title cards and captions, and files that fit each platform. Made for coding agents to drive, so re-recording after a change is one sentence.

![aq's demo, recorded by demo-reel: the camera moves to each agent's pane as it types, idle waits are cut, captions explain each step](docs/demo/aq.gif)

<sub>The demo above was produced by demo-reel from [examples/aq/reel.toml](examples/aq/reel.toml). Every aq call in it is real.</sub>

## What you get

- **One script, every platform.** `x.mp4` for the X timeline (1920×1080 H.264), `readme.gif` and `readme.mp4` for GitHub, each under the platform's size limit.
- **A camera that follows the action.** Each step's start time is logged while recording; the picture shows where things change. The camera eases to that area, and stillness longer than two seconds is cut.
- **Checked before you see it.** Format, length and size limits, a legible first frame, and OCR over every half second for tokens, API keys, home-folder paths and your own private patterns.
- **Made like the launches you scroll past.** It opens on the product, not a title card; the camera pushes in on the lines that change and pulls back at the end; web demos get a large gliding cursor with click ripples; moves carry a touch of motion blur.
- **Narration that reads without sound.** One sentence per step appears as a caption, with keycaps for shortcuts. Optional: a local, natural-sounding voice reads it (Kokoro), or you talk over the film on camera (`reel narrate`).
- **A film and its clips.** Mark steps as feature clips and get 4–15 s loops next to the main film, each as MP4 and GIF.
- **Real, not staged.** Steps that wait for output fail the recording if it never shows, instead of producing a demo of a broken run.

Supported subjects: terminal CLIs (VHS + tmux), iOS apps on a simulator or a real iPhone (agent-device), web pages (agent-browser) and Mac app windows (agent-desktop + screencapture).

## Quick start

```bash
git clone https://github.com/xiatiandeairen/demo-reel ~/demo-reel
ln -s ~/demo-reel/skill ~/.claude/skills/demo-reel   # for Claude Code
~/demo-reel/bin/reel make ~/demo-reel/examples/aq/reel.toml
```

Then ask your agent: "record a demo of this CLI for the README". It writes `docs/demo/reel.toml` in your project, runs `reel make`, and reports the files and the check results.

A terminal script looks like this:

```toml
title = "aq"
subtitle = "A local queue and device lender for parallel AI agents"
url = "github.com/xiatiandeairen/agent-quay"
kind = "terminal"

[terminal]
workdir = "/tmp/aq-demo"     # paths on screen never show your home folder
setup = "setup.sh"

[[pane]]
name = "agent A"
[[pane]]
name = "aq status --top"
run = "aq status --top"
noisy = true                 # a live dashboard: not counted as activity

[[step]]
pane = "agent A"
type = "aq run -- ./build.sh"
wait = "ok"                  # fails the recording if this never appears
caption = "Agent A starts a build"
```

## Commands

| Command | Does |
|---|---|
| `reel make <reel.toml>` | Everything below, in order |
| `reel record <reel.toml>` | `stage.mp4` and `events.json` (step times, pane regions) |
| `reel plan <reel.toml>` | `timeline.json`: camera shots, cuts, captions |
| `reel compose <dir>` | `master.mp4` |
| `reel export <dir>` / `reel check <dir>` | Platform files in `<dir>/out`, then the checks |
| `reel sheet <dir>` | A 24-frame contact sheet of the whole film, for review |
| `reel sync <dir>` | Logged step times against visible changes |
| `reel narrate <dir>` | Plays the film while recording your camera and voice; adds a picture-in-picture presenter and captions from what you said |

Rendering is plain ffmpeg; title cards and captions are drawn by headless Chrome.

## Requirements

macOS, Python 3.11+, ffmpeg, Google Chrome. Terminal demos: vhs, tmux, Homebrew bash. iOS: agent-device and Xcode simulators; a real iPhone also needs agent-device's runner signed by your team (export its `AGENT_DEVICE_IOS_*` variables), the phone unlocked, and Enable UI Automation on. Web: agent-browser. Devices and browsers are borrowed through [aq](https://github.com/xiatiandeairen/agent-quay). Mac windows need an awake display and Screen Recording permission.

Private patterns for the sensitive-text check (company domains, internal hosts) go in `~/.config/demo-reel/private.txt`, one regular expression per line, so they never enter a repository.

## License

MIT or Apache-2.0, at your option.
