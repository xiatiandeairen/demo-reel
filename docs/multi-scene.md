# 多场景总片

状态：已实现（2026-11-22）；用例结果见 `docs/cases.md` 的 CASE-C。

## 一句话方案

每个场景是一条普通的 reel 分镜，用现有录制器各自录好、配好字幕和配音；新增一个总片文件 `film.toml` 按顺序列出场景，`reel compose` 把它们用淡入淡出拼起来，再统一导出和检查。

例子：aq 的完整介绍片由 6 个场景组成。改借用那段时，`reel make examples/aq/borrow.toml` 只重录这一段，再 `reel compose examples/aq/film.toml` 重新拼接，其余场景沿用上次的录制。

## 目标

| # | 目标 | 验收用例 |
|---|---|---|
| G1 | 不懂终端的观众在前 6 秒看懂"几个 agent 共用一台 Mac 会抢资源" | U1 |
| G2 | 同一场景跑两次（没有 aq / 有 aq），观众自己看出构建只跑一次、设备不再打架 | U2 |
| G3 | 借用过程看得见：申请 → 模拟器出现 → 显示自己的页面，两台同时在用 | U3 |
| G4 | 安装在 shell 里真实执行，命令和 README 一致 | U4 |
| G5 | 结尾的数字来自本次录制，能追到日志 | U5 |
| G6 | 别的项目也能写"动画场景加几段不同画面"的分镜，一条命令出片 | U6 |
| G7 | agent-quay 中英文 README 的 mp4 换成新片，访客能播放；GIF 不动 | U7 |

不做：GIF 和原来 30 秒以内的主片、功能短片（保持不变，它们是 GIF 的来源）；X 帖子文案（x-post 负责）；真人出镜；agent-quay 的代码和 README 正文（只换视频链接）。

## 取舍优先级

1. 真实执行，数字可追溯
2. 观众看得懂（G1～G3）
3. 复用现有机制，最轻的技术栈（只用 ffmpeg 和已依赖的 Chrome）
4. 别的项目也能用（G6）
5. 录制速度

## 外形

```
examples/aq/
  film.toml          总片：场景顺序、max_seconds = 90（配音写在各场景里，单独重录时才一致）
  problem.toml       kind = "animation"，配 problem.html
  without-aq.toml    kind = "terminal"，三个窗格加一台共用模拟器
  with-aq.toml       kind = "terminal"，四格调度（原 reel.toml 第 1～6 步）
  borrow.toml        kind = "terminal"，两个窗格加 [[device]] × 2
  result.toml        kind = "card"，值由命令从 runs.log 算出
  install.toml       kind = "terminal"，单窗格
```

`film.toml` 示意：

```toml
title = "aq"
max_seconds = 90
[[scene]]
spec = "problem.toml"
[[scene]]
spec = "without-aq.toml"
# …按顺序列出其余场景
```

命令不新增：

- `reel make film.toml`：依次录制所有场景，再拼接、导出、检查。
- `reel make <场景>.toml`：只重录这一段（场景本身就是普通分镜）。
- `reel compose film.toml`：只重新拼接，用各场景已有的录制。

原来的单场景 `reel.toml` 写法不变。`examples/aq/reel-full.toml` 由总片取代，实施时删除。

## 总览

```
G1 一眼看懂问题    ── animation 场景：HTML/CSS 动画，借来的浏览器逐帧暂停截图（S2）
G2 前后对比        ── without-aq 和 with-aq 用同一套替身脚本
G3 借用看得见      ── terminal 场景的 [[device]]：终端和每台模拟器各录一路，按时间对齐拼进一个画面（S3）
G4 安装真实执行    ── install 场景，临时 CLAUDE_CONFIG_DIR 隔离（S5）
G5 数字可追溯      ── card 场景，值由命令算出（S4）
G6 别的项目能用    ── film.toml 的 [[scene]]，加两种新场景类型，都接进现有录制分发（S1）
G7 替换 README 视频 ── GitHub 网页编辑器上传并在网页提交（见 skill/SKILL.md 交付一节）
```

## 子问题

| # | 问题 | 选择 | 比过的候选 | 胜出理由 |
|---|---|---|---|---|
| S1 | 场景怎么组织 | 每个场景一个分镜文件，`film.toml` 只列顺序 | 一个文件里写 `[[scene]]` 子表；shell 脚本拼成片 | 现有录制器不改、每段可单独重录（优先级 3）；脚本拼接满足不了 G6 |
| S2 | 问题动画 | HTML/CSS 动画，`document.getAnimations()` 逐帧暂停后截图，ffmpeg 合成 | Chrome 画静态图层、ffmpeg 做关键帧；用户提供现成 mp4 | 每帧时刻确定、可重录、能表达变色和相撞；不新增依赖 |
| S3 | 终端和模拟器同框 | VHS 录终端，`xcrun simctl io <设备号> recordVideo` 录每台模拟器，按开录时刻对齐后排成左终端、右手机 | 录桌面上摆好的真实窗口 | 不受其他窗口、通知、别的会话模拟器干扰，每次画面一致 |
| S4 | 结尾数字 | 替身 `build.sh` 每真跑一次往 `runs.log` 写开始、结束时间；卡片两行："Builds run: N → M"、"Build time: X s → Y s" | 手写数字；加 "0 device clashes" | 手写违反 G5；抢设备次数量不出来，不写 |
| S5 | 安装段 | 照实运行 `brew install`（本机已装，输出 already installed，镜头停在命令行），两条 `claude plugin` 命令在临时配置里真实全新安装 | 先卸载再装；`brew reinstall`；Claude Code 界面里输斜杠命令 | 卸载会让本机其他会话的 aq 调用失败；reinstall 与 README 不一致且没装过的人会报错；Claude Code 界面会露出账号信息 |

最简可行形态是"shell 脚本拼 6 个成片 + 手写数字 + 只录终端"。推荐方案多出的部分：`film.toml` 换来 G6 和整片检查；逐帧动画换来可重录；`[[device]]` 是 G3 必需；命令算数是 G5 必需。

## 场景分镜

| # | 时长 | 布局 | 动作 | 旁白 |
|---|---|---|---|---|
| 1 问题 | 6 秒 | 动画 | 三个标着 A/B/C 的 agent 图标滑进 Mac 轮廓，三块构建堆进去，CPU 条由绿到红；两个图标冲向同一部手机，相撞后抖动、闪红。扁平图标，配色沿用 accent `#1f3b8f`、`#1596b8` | "Three agents. One Mac." |
| 2 没有 aq | 约 10 秒 | 左三个窗格 A/B/C，右一台共用模拟器 | 三人几乎同时 `./build.sh`；A `sim-open A`，B 接着 `sim-open B`，右边从蓝色 "Agent A" 变成黄色 "Agent B" | "Every agent builds alone." / "And they fight over one simulator." |
| 3 调度 | 约 20 秒 | 四格终端 | 原 reel.toml 第 1～6 步 | "With aq, the same build runs once." / "Heavy work waits its turn." |
| 4 借用 | 约 20 秒 | 左两个窗格 A/B，右两部手机 | A `aq hold ios-sim` 得到 held 后 `sim-open A`，手机变蓝；B 同样，手机变黄；开机等待被自动剪掉 | "Each agent borrows its own simulator." / "Nobody steps on anyone." |
| 5 结果 | 4 秒 | 文字卡 | S4 的两行数字 | 无 |
| 6 安装 | 约 10 秒 | 单窗格，字号 52 | `brew install xiatiandeairen/tap/aq`、`claude plugin marketplace add xiatiandeairen/agent-quay`、`claude plugin install agent-quay@agent-quay`，结尾卡放仓库地址 | "Install with Homebrew. Add the Claude Code plugin." |

`sim-open` 是准备脚本里的小命令：`xcrun simctl openurl <设备号> http://localhost:<端口>/<A|B>.html`，再每 0.3 秒截一次模拟器屏幕，等到页面颜色真的出现才打印 "Agent A's page is up" 并返回，步骤用 `wait` 等这一行（录屏时机器忙，页面加载实测 3～6 秒；这段空等在成片里被剪掉）。分镜开头注释写明。页面服务用系统的 `/usr/bin/python3`：pyenv 的 python3 垫片在后台启动时会卡住不监听端口（实测）。替身构建以低优先级（nice）跑，免得拖慢模拟器。场景 2 两人用同一个设备号（准备阶段 `aq hold` 借一台），场景 4 各用自己借到的。不用 `booted`：本机别的会话也开着模拟器，`booted` 可能打到别人的设备。场景之间用现有 `compose_ffmpeg.XFADE` 的淡入淡出。

## 机制细节

**逐帧动画（S2）**：浏览器里的 CSS 动画平时按真实时间播放，截图时刻不可控。把页面上所有动画暂停，再把每个动画的 `currentTime` 设到第 n 帧的时刻（n / 30 秒）后截图，第 n 张图就精确对应第 n 帧，与机器快慢无关。浏览器经 `aq hold browser` 借用，用 agent-browser 的 `eval` 和 `screenshot` 驱动。

**录制与合成分开**：终端原始录像存为 `stage-term.mp4`，每台手机的录像存在 `devices/`，开录时刻写进 `events.json`；拼成 `stage.mp4` 的那一步在录制结束和每次 `reel plan` 时都会重做，改排布或对齐不用重录（2026-11-22 dogfood：此前修一个对齐 bug 要整段重录 5 分钟）。

**等待可压缩**：步骤写 `squeeze = true` 时，planner 把这一步命令运行的中段从保留区间里剪掉（开头留 0.5 秒、结尾留 1.5 秒，旁白时段不剪），用于页面加载、克隆这类画面在动、却没有信息的等待。

**模拟器同框（S3）**：每台借到的模拟器在 `recordVideo` 开录时记下墙钟时刻，终端录制已有墙钟对齐（状态栏标记格），合成时按两者的差值平移，使同一时刻的画面对齐。

**结尾数字（S4）**：`result.toml` 里每个值写一条命令，例如 `wc -l < $REEL_WORK/runs-without.log`，在各场景录完后执行，输出填进卡片；命令失败或输出为空则出片失败，不出带错数字的片子。

## 横切项

- 数据归属：每个场景的中间产物在它自己的状态目录（`$XDG_STATE_HOME/demo-reel/<片名>-<短哈希>/`，按场景分镜路径区分）；总片目录只放拼好的成片和整片检查结果。`runs.log` 在演示工作目录里，是结尾数字的唯一来源。
- 并发与时序：场景按顺序录。模拟器、浏览器经 aq 借用，场景结束或失败时都归还。
- 持久化与迁移：不涉及。单场景分镜格式不变。
- 可观测：每个场景和整片都跑检查；整片出一张联系表。
- 演进：新场景类型接进 `cli._record` 的分发。

## 出错与恢复

| 场景 | 表现 | 恢复 |
|---|---|---|
| 某个场景录制失败 | 整片停下，报出场景名和步骤 | 修好后只重录这一段，再 `reel compose film.toml` |
| Safari 第一次打开黑屏数秒（原型实测） | 场景 2/4 的页面来不及出现 | 准备脚本先在每台模拟器上打开一次 Safari |
| 本机网页服务未就绪（原型实测"无法连接"） | 页面显示连接失败 | 准备脚本轮询服务就绪后才开录 |
| 页面加载有 1～2 秒延迟（原型实测） | 页面晚于命令出现 | 每步 hold 留足 2.5 秒 |
| 结尾数字命令失败 | 出片失败 | 看 `runs.log` 是否写入 |
| 整片超过 90 秒或 readme.mp4 超过 10 MB | 检查 BAD | 缩短场景 hold，或降 readme.mp4 码率 |

## 证据

| 项 | 等级 | 内容 |
|---|---|---|
| 临时 Claude 配置隔离 | 已运行 | 临时 `CLAUDE_CONFIG_DIR` 里 marketplace add 和 install 共 7 秒；之后用户自己的 `claude plugin list` 不含 agent-quay |
| 后台录模拟器 | 原型实验 | 无窗口录出 1206×2622 H.264，10 秒时长准确 |
| B 顶掉 A | 原型实验 | 连切 3 轮均复现，加载延迟 1～2 秒 |
| 逐帧渲染速度 | 原型实验 | 借来的浏览器 30 帧 2.0 秒；每帧单独启动 Chrome 为 2.5 秒一帧，已排除 |
| 借模拟器耗时 | 已运行 | `aq hold ios-sim` 34.8 秒 |
| 两部手机与终端时差在 0.3 秒内 | 推演 | T3 样片验证 |
| 整片约 70 秒、不超过 10 MB | 推演 | 按上一版 49 秒 5.0 MB 估算；T6 验证 |

## 任务

| # | 任务 | 完成标准 |
|---|---|---|
| T1 | `film.toml` 解析和场景拼接（`reel compose`、`reel make` 识别总片） | 两个现成场景拼成一条，检查通过，联系表看得到转场 |
| T2 | `animation` 场景类型 | `problem.html` 渲染出 6 秒 30 帧每秒的视频，一分钟内完成 |
| T3 | terminal 场景的 `[[device]]` | 10 秒的借用样片，两部手机与终端时差不超过 0.3 秒 |
| T4 | `card` 场景类型，值由命令算出 | 单元测试通过；数字与 `runs.log` 一致 |
| T5 | aq 的 7 个分镜文件和准备脚本，删除 `reel-full.toml` | 每个场景单独 `reel make` 通过 |
| T6 | 整片出片、审片、用户看片 | 检查全部通过 |
| T7 | 更新 SKILL.md、README（中英）、`problem-model.md`（主片 30 秒之外加"完整介绍片，上限 90 秒"）、测试 | 测试全部通过 |
| T8 | 替换 agent-quay README 视频 | 推送前经用户同意；未登录浏览器确认能播放 |

## 验收用例

| # | 目标 | 情形 → 期望 |
|---|---|---|
| U1 | G1 | 场景 1 第 3～5 秒的帧里能看到两个图标相撞 |
| U2 | G2 | 场景 2 右边的手机先显示 "Agent A"，后变成 "Agent B" |
| U3 | G3 | 场景 4 最后 3 秒两部手机同时显示各自页面；手机变化在命令之后、成片时间 3 秒以内 |
| U4 | G4 | 录制前后用户的 `claude plugin list` 相同 |
| U5 | G5 | 卡片数字等于 `runs.log` 算出的值；只跑了 2 次就写 2 |
| U6 | G6 | todomvc 网页场景加一个动画场景能拼出成片 |
| U7 | G7 | 中英文 README 在未登录浏览器里都能播放新视频 |
