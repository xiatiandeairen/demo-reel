---
name: demo-reel
description: 录产品演示视频和 GIF：给终端 CLI、iOS 模拟器 App、网页或 Mac 窗口录一条 30 秒内、发 X 和放 GitHub README 用的演示时使用；写分镜、真实执行、自动推拉镜头和剪空等、加标题卡和标注、按平台导出并检查大小和敏感信息。用户说"录个 demo""做个 GIF""给 README 配个演示视频""重录演示"时用。
---

# demo-reel

把一份分镜文件（`reel.toml`）变成一条成片：真实执行每一步并记下时间，按画面变化推拉镜头、剪掉空等，加标题卡和标注，导出 X 用的 mp4、README 用的 GIF 和 mp4，最后检查。命令是本 skill 目录里的 `reel`（指向仓库的 `bin/reel`），下文直接写作 `reel`。

## 做法

1. 写分镜：放在被演示项目里，通常是 `docs/demo/reel.toml`，演示要用的准备脚本、替身脚本放在它旁边，以后改了代码一句话就能重录。字段见仓库里 `reel/spec.py` 和各录制器文件开头（终端 `reel/record_terminal.py`，iOS `record_ios.py`，网页 `record_web.py`，Mac `record_mac.py`），写法参考 `examples/`；仓库根目录是 `reel` 这个软链所指文件的上两级。
2. 出片：`reel make docs/demo/reel.toml`。产物都在 `docs/demo/.reel/out/`：`x.mp4`、`readme.gif`、`readme.mp4`、`check.json`。把 `docs/demo/.reel/` 加进项目的 `.gitignore`，只提交最后要用的 GIF 或 mp4。录的是 PATH 上的工具；要录当前检出的构建，在准备脚本里先编译，再把产物目录放到 PATH 前面。
3. 看检查：`reel make` 最后打印检查结果，有 BAD 就修到全部 ok。泄露截图在 `out/leaks/`。
4. 自己审片：`reel sheet docs/demo/.reel` 出一张覆盖全片的联系表（24 格，`out/sheet.png`），逐格看：首帧是不是标题卡、每个镜头框住的是不是正在变的地方、标注和画面是否对得上、有没有截断或错位。
5. 交付：告诉用户每个文件的路径、时长、大小、检查结果和你审片看到的问题。发布、上传由用户做；帖子文案交给 x-post。

## 分镜怎么写

- 一条只讲一件事："问题 → 操作 → 结果"，3～8 步，成片 30 秒内（标题卡和结尾卡各约 1.8 秒）。
- 每步一个 `caption`，6～8 个英文词，说这一步发生了什么、为什么值得看，不复述命令本身。
- 打字按每字 45 毫秒上屏（`[terminal] typing_ms` 可调），80 个字符的命令约 3.6 秒；命令尽量短，长路径先放进准备脚本或别名。
- 结论要看得见：关键数字或结果单独打印一行（如 `build 5.1s → 1.5s`），不要埋在长行中间。
- 被演示的工具真实运行，不伪造输出。耗时太长的依赖可以用替身脚本，在分镜开头注释里写明谁是替身。长等待不用自己剪，录制后会自动剪掉。
- 终端演示在 `/tmp` 下的中性目录里跑（`[terminal] workdir`，每次录制前会被清空），画面里不出现家目录路径；准备脚本以 `bash setup.sh <workdir>` 调用。单窗格用 `font_size = 36`～`40`，否则缩到 README 宽度看不清；要多个窗格时用 `[[pane]]`，一直在刷新的看板标 `noisy = true`。
- 演示里有意让某条命令失败时，那一步写 `allow_fail = true`，否则非零退出会让录制失败。
- 每个会等待的步骤写 `wait`（终端是整屏文字上的正则，网页和 iOS 是选择器，如 iOS 的 `text="Done"`、`value="36"`），等不到就失败，不会带着错误画面出片。终端的 `wait` 会匹配到屏幕上已有的旧输出：等第二次出现写成 `ok[\s\S]*ok`。
- iOS 真机：`[ios] device = "physical"`，经 aq 借用户登记过的 iPhone；运行前在环境里设好 agent-device 的签名变量（项目或工作区说明里有就照用，不写进分镜）。手机要解锁、自动锁定设为永不、打开 Enable UI Automation，这些只能请用户做。真机的状态栏、通知、账号名会原样录进去，挑不含个人信息的 App 和页面。按钮名跟着手机语言走，先 `agent-device open <app>` 看快照里的名字再写分镜；即时响应的 App 加 `settle = false`，否则每步要等 3 秒左右。
- 镜头：终端步骤默认对准打字的窗格；不写 `focus` 的看看步骤会跟着画面变化走。只在确定这一步只有那一处在变时才写死 `focus`，否则别处同时变化时镜头不会跟过去。单窗格里输出行很长时写 `focus = "full"`，避免推近后截断行。网页、Mac 跟着画面变化走；iOS 始终显示整台手机。

## 出错时

| 现象 | 怎么办 |
|---|---|
| `step N failed` / `exited with` | 演示本身出错了。如实告诉用户哪一步、什么输出；不要为了出片改被演示项目的代码 |
| `sensitive text` 为 BAD | 看 `leaks/` 截图，改分镜或准备脚本让它不出现，再重录；不要只改检查规则 |
| `readme.gif size` 为 BAD | 缩短演示或减少整屏变化；GIF 上限可用 `gif_max_mb` 调低，不能调高过 10 |
| `no active display`（Mac） | 屏幕没亮或已锁定，请用户在场时再录 |
| 镜头切得早或晚 | 看 `reel sync <目录>` 的 delta；终端录制会用每条命令回车的时刻自动校正 |

## 依赖

python3 ≥ 3.11、ffmpeg、Google Chrome；终端加 vhs、tmux、Homebrew bash；iOS 加 agent-device；网页加 agent-browser；模拟器和浏览器都通过 aq 借用。
