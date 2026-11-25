# demo-reel

[English](README.md) · 简体中文

给 coding agent 用的 skill：把一份简短的剧本变成能发布的产品演示，包括发 X 和 YouTube 用的片子、README 用的 GIF 和视频。命令真实执行，镜头跟着动作走，空等被剪掉，每一步都有字幕，文件符合各平台的限制。代码改了以后，对 agent 说一句话就能重录。

![demo-reel 录的 aq 演示：镜头随打字的窗格推拉，空等被剪掉，每一步有字幕](docs/demo/aq.gif)

<sub>上面这段由 demo-reel 根据 [examples/aq/cli](examples/aq/cli) 生成，里面每次 aq 调用都是真实执行。</sub>

## 能得到什么

| 文件 | 用在哪 | 内容 |
|---|---|---|
| `share.mp4`（1920×1080 H.264 High） | X、YouTube | 完整的故事，90 秒以内：钩子、问题、常见做法为什么不行、你的工具、结果、怎么安装 |
| `readme.mp4`（1280×720，不超过 10 MB） | README 里的视频 | 同上，去掉钩子和亮出名字 |
| `assets/<名字>.gif`（不超过 10 MB） | README 首屏 | 一个场景，30 秒以内，循环播放 |

- **真实录制。** 写了"等待某段输出"的步骤，等不到就判失败，不会产出一段跑坏了的演示。每个场景录之前先不录屏预演一遍。
- **镜头跟着动作走。** 推近到正在变化的那几行，结尾拉回全景；手机、网页、Mac 窗口完整显示。
- **静音也看得懂。** 每一步都有字幕。可选本地配音（Kokoro，中文或英文），或者你自己边看边讲、出镜（`reel narrate`）。
- **数字来自录制。** 结果卡和计时进度条都由场景的录制日志算出来，不手写。
- **交付前先检查。** 大小、格式和时长上限；每半秒做一次文字识别，查 token、密钥、家目录路径和你自己的私有规则；配音响度；交付物是不是来自最新的剪辑。
- **只重做变了的部分。** 只改一句字幕，不用重录，只重新剪辑。

支持的对象：终端 CLI（VHS + tmux）、iOS 和 Android 的模拟器或真机上的 App（agent-device）、网页（agent-browser）、Mac 应用窗口（agent-desktop + screencapture）。只支持 macOS。

## 快速开始

```bash
git clone https://github.com/xiatiandeairen/demo-reel ~/demo-reel
ln -s ~/demo-reel/skill ~/.claude/skills/demo-reel   # 给 Claude Code 用
~/demo-reel/bin/reel make ~/demo-reel/examples/hello/cli/reel.toml
```

之后对 agent 说"给这个项目录个 README 用的演示"。它写剧本之前，先和你对齐：语言、风格、GIF 讲哪一件事、场景表、每一句字幕、每个数字从哪来。然后把剧本写进你项目的 `.agents/demo-reel/<名字>/`，准备好演示环境，运行 `reel make`，看联系表审片，最后把文件报给你。

一套剧本是一个目录：

```
.agents/demo-reel/cli/
  reel.toml          语言、风格、每个文件用哪些场景、结果卡
  scenes/with.toml   一个场景：打什么、点什么，等什么出现，字幕写什么
  scripts/           agent 写的准备和重置脚本
```

## 命令

| 命令 | 作用 |
|---|---|
| `reel make <reel.toml> [--rerecord]` | 预检、配音、预演、录制、剪辑、卡片、拼接、导出、检查、联系表；只重做变了的部分。`--rerecord` 强制重录，比如被演示的工具升级以后 |
| `reel narrate <reel.toml> [--cut share\|readme]` | 你自己运行：边看成片边讲，录下摄像头和声音，生成右下角出镜小窗和由你的话生成的字幕 |

## 文件放在哪

剧本放在你的项目里（`.agents/demo-reel/<名字>/`），GIF 输出到 `<项目>/assets/<名字>.gif`，不会覆盖不是 demo-reel 写的同名文件。其他文件按 XDG 目录放：录像和剪辑在 `$XDG_STATE_HOME/demo-reel/`（默认 `~/.local/state`），mp4、检查报告和联系表在 `$XDG_DATA_HOME/demo-reel/`（`~/.local/share`），配音模型在 `$XDG_CACHE_HOME/demo-reel/`（`~/.cache`）。敏感信息检查的私有规则（公司域名、内网主机名）写在 `~/.config/demo-reel/private.txt`，每行一个正则表达式，这样它们不会进任何仓库。

## 依赖

macOS、Python 3.11+、ffmpeg、Google Chrome。终端：vhs、tmux、Homebrew bash。iOS：agent-device 和 Xcode；Android：agent-device 和 Android SDK（adb、emulator）；真机要解锁，并打开 UI 自动化或 USB 调试。网页和动画：agent-browser。Mac 窗口：agent-desktop，屏幕亮着，有屏幕录制权限。配音：uv（第一次用时安装 Kokoro）。

## 许可

MIT 或 Apache-2.0，任选其一。
