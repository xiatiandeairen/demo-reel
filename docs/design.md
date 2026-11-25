# 设计

demo-reel 怎么实现 `docs/problem-model.md` 定下的目标：职责怎么分、命令、剧本格式、流程和存储、各端录制。2026-11-24 定稿。

## 职责

| 谁 | 做什么 |
|---|---|
| skill | 和用户对齐剧本（语言、风格、主片讲哪件事、场景表、字幕、数字来源），写剧本；看联系表审片 |
| agent | 准备演示环境、准备设备、写准备和重置脚本；把制品放进 README、上传、发布 |
| CLI | 预检、调用重置、预演、驱动演示并录屏、后期、导出、机器检查、生成联系表 |

原则：CLI 只做确定的事，以及 AI 看不出来的检查；要判断、要对话、要对外的事归 skill 或 agent。

## 命令

    reel make <剧本>       预检 → 配音 → 预演 → 录制 → 后期 → 卡片 → 拼接 → 导出 → 检查 → 联系表
                           只重做输入变了的阶段；--rerecord 强制重录（被演示的工具升级后用）
    reel narrate <剧本>    用户亲自运行：边看成片边讲，生成出镜版

输出给 agent 看：进度逐行打印，结尾分四块——交付物（路径、时长、大小）、机器检查、审片用的联系表、PASS 或 FAIL。
失败时写清阶段、场景、步骤、原因和建议的处理办法。
检查不通过时不写 GIF；`assets/` 里已有一个不是 demo-reel 写的同名文件时，报错停下。

## 项目里的文件

一个项目可以有多套制品，每套一个子目录：

    <项目>/.agents/demo-reel/<名字>/
      reel.toml          总剧本
      scenes/<id>.toml   要录制或渲染的场景；id 就是文件名
      scenes/<id>.html   问题动画页面
      scripts/           agent 写的准备、重置和替身脚本
    <项目>/assets/<名字>.gif

### reel.toml

| 字段 | 含义 |
|---|---|
| `lang` | `en` 或 `zh`；决定字幕字体、换行方式和配音声音 |
| `narrate` | 要不要配音，默认不配 |
| `accent` | 可选，两种颜色，用于背景渐变和卡片；不写就用默认配色 |
| `[share].scenes` | 站外版（X、YouTube）的场景顺序 |
| `[readme].scenes` | README 版的场景顺序 |
| `[gif].scene` | 主片是哪一个场景 |
| `[card.<id>]` | 卡片：`lines`（文字行）、`values`（每个值是一条命令的输出）、`bars`（条形图，值可以是命令，或某个场景的计时条） |

占位符：`{<值名>}` 换成 `values` 里对应命令的输出；`{files:<场景 id>}` 换成那个场景录制时保存的文件目录。

### 场景

| 字段 | 适用 | 含义 |
|---|---|---|
| `kind` | 全部 | `terminal`、`ios`、`android`、`web`、`mac`、`animation` |
| `reset` | 全部，可选 | agent 提供的重置命令；预演和录制之前各调用一次 |
| `workdir`、`init`、`keep_files` | 终端 | 窗格从哪个目录开始；每个窗格开始前执行、不出现在画面上的命令；录完要保存的文件 |
| `[[pane]] name`、`run` | 终端 | 窗格名；开录前就启动的看板命令 |
| `[[device]] name`、`find` | 终端 | 并排设备的标签；一条打印设备号的命令（设备可以在演示中途才出现） |
| `app`、`device`、`settle` | iOS、Android | 演示的 App；设备号（写成环境变量）；每步之后要不要等界面安静下来 |
| `url` | 网页 | 打开的页面 |
| `app` | Mac | 演示的 App |
| `html` | 动画 | 动画页面 |

每一步可以写的字段：

| 字段 | 适用 | 含义 |
|---|---|---|
| `say` | 全部 | 字幕和配音；第一步必须写，没写的步骤沿用上一句 |
| `wait` | 全部 | 要等到出现的内容；等不到就判录制失败 |
| `hold` | 全部，可选 | 这一步之后停多久；默认按配音或阅读时长自动推出 |
| `pane`、`type`、`focus`、`squeeze`、`timer` | 终端 | 在哪个窗格打字；打什么命令；镜头推到哪里（默认推近到打字的窗格里变化的几行，没打字的步骤用全景；全景要写 `focus = "full"`）；剪掉中间的空等；画计时条 |
| `click`、`fill`、`type`、`key`、`scroll`、`back` | iOS、Android、网页、Mac | 统一的操作动词；选择器的写法由各端工具决定 |

### 自动推导，不用写

| 项 | 规则 |
|---|---|
| 终端字号 | 4 个窗格及以上用 40，否则用 52 |
| 窗格排列 | 有并排设备时上下排列，否则网格排列 |
| 看板 | 写了 `run` 的窗格算看板，它的刷新不算画面变化 |
| 等待超时 | 预演时这一步的实际耗时乘以安全系数 |
| 开场停留 | 片子的第一个场景停 1.5 秒，后面的场景停 0.6 秒 |
| 计时条比例尺 | 取这一版里最长的那次计时 |
| 卡片和动画的时长 | 按动画结束或配音结束的时刻 |
| 按键徽标 | 从 `key` 动词推出 |
| 配音声音 | 由 `lang` 决定 |

## 流程和存储

XDG 目录（下文的 `state`、`data`、`cache`、`config` 分别指 `$XDG_STATE_HOME`、`$XDG_DATA_HOME`、`$XDG_CACHE_HOME`、`$XDG_CONFIG_HOME` 下的 `demo-reel/`）：

    state/<项目名>-<名字>-<路径短哈希>/
      scenes/<id>/rehearsal.json
      scenes/<id>/take/   stage.mp4  events.json  files/  stamp.json
      scenes/<id>/edit/   timeline.json  scene.mp4  stamp.json
      cuts/{share,readme,gif}/  master.mp4  cut.json  stamp.json
      presenter/          真人出镜时摄像头和麦克风的原始录制
    data/<同名>/          share.mp4  readme.mp4  出镜版  report.json  sheet-*.png  leaks/
    cache/                配音片段（按文字和声音的哈希存）、配音和语音识别的环境与模型
    config/private.txt    用户自己的私有检查规则

不同 worktree 的剧本路径不同，所以各用各的目录，录像不共享。

| 阶段 | 读 | 写 |
|---|---|---|
| 预检 | 场景的 `kind`、`workdir`、`find` 或 `device`；屏幕状态和录屏权限 | 无 |
| 配音 | `say`、`lang` | `cache` 里的配音片段；每句时长交给后面的阶段 |
| 预演 | `reset` 和场景的全部字段 | `rehearsal.json`：`stamp`、`ok`、`problems[]`、`seconds[]`（每步耗时） |
| 录制 | `reset`、场景的全部字段、每步耗时、配音时长 | `take/`：`stage.mp4`；`events.json`；`files/`；`stamp.json` |
| 后期 | `take/`、`say`、`focus`、`squeeze`、`timer`、`accent` | `edit/`：`timeline.json`；`scene.mp4`；`stamp.json` |
| 卡片 | `[card.<id>]`、各场景 `take/files/` | `scenes/<卡片 id>/edit/` |
| 拼接 | 三种制品的场景顺序、各场景 `edit/` | `cuts/<名字>/`：`master.mp4`；`cut.json`；`stamp.json` |
| 导出 | `cuts/*/master.mp4` | `share.mp4`、`readme.mp4`；检查通过后写 `assets/<名字>.gif` |
| 检查 | 交付物、`private.txt`、`cuts/*/stamp.json`、上一次的 `report.json` | `report.json`、`sheet-*.png`、`leaks/` |

各文件的字段：

- `events.json`：
  - `stage`：路径、宽、高、时长、帧率；
  - `regions`：名字 → 画面上的矩形；
  - `beats[]`：`start`、`end`、`focus`、`ignore`、`pane`、`narration`；
  - `commands[]`：`pane`、`start`、`end`、`exit`；
  - `sync.method`。
- `timeline.json`：
  - `stage`；
  - `keep`：保留的时间段；
  - `shots[]`：`t`、`x`、`y`、`zoom`；
  - `captions[]`：`start`、`end`、`text`；
  - `timers[]`；
  - `narration[]`：`wav`、`start`；
  - `style`：`accent`、`kind`。
- `cut.json`：`scenes[]`（`id`、`start`、`seconds`），以及总长 `seconds`。
- `report.json`：
  - `deliverables[]`：`name`、`path`、`seconds`、`bytes`、`cut_stamp`；
  - `checks[]`：`name`、`ok`、`detail`；
  - `gif_written`：路径和内容哈希。

**新鲜度：** 每一层的 `stamp.json` 记下这一层输入的指纹。`make` 从上往下比对，指纹相同就复用，不同就从这一层往下全部重做。

| 层 | 指纹包含什么 |
|---|---|
| 录制 | 场景剧本 + 它引用的脚本和页面 + `lang` + 配音时长 |
| 后期 | 录制的指纹 + 剧本里后期用到的字段 |
| 拼接 | 各场景后期的指纹 + 场景顺序 |
| 交付物 | 在 `report.json` 里记下来自哪次拼接；检查时核对，对不上就报"过期" |

被演示的工具在剧本目录之外，它升级了指纹看不出来，要用 `--rerecord` 强制重录。

## 各端录制

| 端 | 驱动和录屏 | 保持画面干净 |
|---|---|---|
| 终端 | VHS + tmux；shell 钩子记录每条命令的起止时间 | 在中性的工作目录里演示；CLI 自己的临时文件放在状态目录，不放在工作目录 |
| iOS、Android（模拟器和真机） | 共用一个录制器，都用 agent-device | 模拟器：录前固定状态栏，录完恢复；Android：开启演示模式，录完关掉；iPhone 真机改不了状态栏，预检时提醒用户 |
| 网页 | agent-browser；注入光标脚本 | 地址栏里不出现内网地址 |
| Mac | agent-desktop 驱动，screencapture 只录目标窗口 | 窗口不能被遮挡 |
| 动画 | 无界面的 Chrome 逐帧截图 | — |

- 所有端都先预演再录制，每次之前都调用 `reset`。
- 改过的设备设置，录完一律恢复。
- Android 的录像只在画面变化时才写入一帧，要先转成固定帧率；单段录像最长 180 秒。
