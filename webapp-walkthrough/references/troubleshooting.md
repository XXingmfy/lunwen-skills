# 排障手册

按"症状 → 原因 → 处理"排列，全部来自实机踩过的坑。

## 1. 发现阶段

### `plan.json` 里 modules 为空
- 原因：`menuSelector` 不匹配，或菜单渲染在 iframe / shadow DOM 外层容器里。
- 处理：先用 ego 打开页面取一次快照，看菜单节点的 role 与 class，再改选择器；iframe 内的菜单当前不支持自动发现，手工在 `config.json` 里用 `menuHrefs` 兜底并跳过 discover。

### 选项卡数量不对
- 原因：`tabSelector` 抓到了非选项卡元素，或选项卡懒渲染（点击后才生成）。
- 处理：改成更精确的选择器；懒渲染场景把 `tabSelector` 设成 `.el-tabs__item` 这类固定 class，并在 `settleMs` 上给足等待。

### 模块被误点（退出登录、删除）
- 处理：`skipPaths` 加路径，`denyButtons` 加按钮文案。脚本默认只点 `safeButtons` 白名单里的按钮。

## 2. 录制阶段

### 成片里只有一帧 / 大片空白
- 原因 1：还在用 `Page.startScreencast` + `Page.screencastFrameAck`。新版 ego（0.6.3.17）的 `Page.cdp` 禁止在 params 里带 `sessionId`，而 ack 又必须带，二者冲突 → 只出 1–3 帧就卡死。
- 原因 2：抽帧与驱动分在两个进程里并发跑。
- 处理：本版已改用 `page.cdp("Page.captureScreenshot", {format:"jpeg"})` 轮询抽帧（同进程、按变化去重），不再需要 screencast / ack。若你自行扩展，务必保持"驱动与抽帧同进程"。

### 抽帧太慢 / 录制时间过长
- 原因：`captureScreenshot` 每次约 200–300ms，是硬上限（约 3–4 fps）。
- 处理：这属正常；成片靠"定格 + 配音"补节奏，不必追求高帧率。想更快可调小 `recorder.jpegQuality`。

### 页面跳转后画面丢失
- 原因：`captureScreenshot` 在导航瞬间可能失败。
- 处理：`captureOnce()` 已用 try/catch 忽略瞬时失败；导航后 `hold(settleMs)` 让新页首帧进入。

### 帧尺寸不一致导致合成失败
- 症状：`concat` 报 resolution 不匹配。
- 原因：`Emulation.setDeviceMetricsOverride` 生效前后各有关键帧。
- 处理：`assemble.py` 已按出现最多的尺寸过滤异常帧；若仍失败，把 `recorder.width/height` 设为页面自然尺寸。

### 想录浏览器窗口而不是页面
- 结论：**不可行**。ego lite 的任务窗口不参与桌面合成，`gdigrab` 截出来是纯白（实测 cloaked=0、visible=1 但内容不绘制），`PrintWindow` 同样返回空白。
- 处理：坚持用 CDP 抽帧。页面级录制反而没有地址栏干扰，适合做演示片。

## 3. 交互阶段

### 点击时报 `matched 2 elements`
- 原因：用文本/标签定位时命中了隐藏面板里的同名元素，或复用了同一个临时 id。
- 处理：脚本现已采用"先筛选可见节点 → 打 `data-wt` 标记 → 按属性选择器点击"，且每次标记唯一。自己写扩展逻辑时不要复用固定 id。

### 填值后页面行为异常
- 原因：改写目标元素的 `id` 会破坏页面自身的 `getElementById` 定位（实测导致查询框取值为空）。
- 处理：只用 `data-wt` 之类的附加属性做标记，**不要改 id/name**。

### 接口报错没被记录
- 原因 1：错误发生在 `hold()` 之外的窗口期，事件被后续动作消费。
- 原因 2：请求由 Service Worker 处理，`Network` 域看不到。
- 处理：把关键动作后的 `hold(settleMs)` 保留；SW 场景改为断言页面可见状态（错误提示、空列表）。

### 表单提交后数据被写脏
- 处理：`testQuery` 统一加前缀；只在 `safeButtons` 里放查询类按钮；需要写入的场景先准备测试库或提供清理接口。

## 4. 讲解与合成

### 没有声音
- 原因 1：SAPI 音色名与系统不符。
- 原因 2：选了 `edge` 但机器断网 / 未装 edge-tts，且未回退成功。
- 处理：`engine` 留空让脚本按 `name` 自动选（`zh-CN-*` 走 edge，否则 sapi）；`voice.name` 删掉则 SAPI 自动挑第一个 zh-CN。断网时把 `engine` 设为 `sapi`（离线 Huihui）。`voice.rate` 范围 -10~10。

### 讲解太长，画面定格太久
- 原因：中文 TTS 约 4 字/秒，每段超过 6 秒就会明显拖沓。
- 处理：每段控制在 20 字以内；或调 `voice.rate` 到 2–3；或写 `narration.json` 精修。

### 字幕太大 / 不显示中文
- 原因：libass 的字号随分辨率缩放；缺少中文字体。
- 处理：`assemble.py` 里 `FontSize` 按 1440×860 调到 12；字体走 `C:/Windows/Fonts/msyh.ttc`。

### ffmpeg 找不到
- 处理：`winget install Gyan.FFmpeg`，脚本会到 winget 包目录里找 `ffmpeg.exe`；也可把 ffmpeg 加入 PATH。

### `Unrecognized option 'vsync'`
- 原因：ffmpeg 7+ 移除了 `-vsync`。
- 处理：用 `-fps_mode cfr`（脚本已改）。

## 5. 环境类

### `ego's nodejs process exited with code 1` 且无堆栈
- 原因：脚本里有顶层语法错误，或 stdin 被 shell 破坏（PowerShell 5.1 尤其容易）。
- 处理：用 Git Bash 的 `ego-browser nodejs < script.mjs`；PowerShell 下用 `-e "await import('file:///...')"` 引导。

### 中文字符串变成 `????`
- 原因：Windows 控制台 GBK 编码。
- 处理：只是显示问题，文件内容正常；需要看日志时用 `PYTHONIOENCODING=utf-8`。

## 6. 教学脚本（lesson.json）

### 某一步选择器找不到 / 点击报匹配多个
- 现象：该功能点在 `功能点清单.md` 标 ❌，`steps.jsonl` 里有 error。
- 处理：看 `run/shots/` 该步截图确认实际 DOM；把 `selector` 换成更精确的，或用 `text`，或用 `>> nth=0`。
- Element Plus 表格按钮常匹配多个：`"selector": ".el-table__body .el-button >> nth=0"`，并配 `"findSelector": ".el-table__body .el-button"` 做高亮。

### 高亮框 / 光标位置不对
- 原因：`highlight` / `findSelector` 指向了隐藏元素或包裹层。
- 处理：换成更贴近可点击元素的 selector（如 `.el-dialog`、`.el-drawer`、`.el-table__row`）。

### 章节卡没有出现
- 原因：`chapters[].card` 被设成 `false`，或该章 `firstUrl` 导航失败导致覆盖层未注入。
- 处理：去掉 `card:false`；确认该章第一步的 `url` 可访问。

### 登录后后续页面又跳回登录
- 原因：token 没进 localStorage，或用了新的 page。
- 处理：登录必须在同一 `page` 上真实提交（本版写成一章一步，token 存同源 localStorage，后续 goto 仍登录）。

### 视频里没有字幕 / 字幕是豆腐块
- 处理：确认系统有 `C:/Windows/Fonts/msyh.ttc`；`assemble.py` 的 `subtitles=...FontName=Microsoft YaHei` 已指定。

### 解说太长，某步定格过久
- 处理：每步 narration 控制在 30–60 字；或调 `voice.rate` 到 2–3；或 `--narrate-only --script narration.json` 精修台词不重录。

## 7. 上传到云效（publish）

### 提示 publish.enabled=false / 没有上传
- 原因：配置未开启，也没加 `--publish`。
- 处理：`config.json` 里 `publish.enabled=true` 并填好 `repo`；或命令加 `--publish`。

### 推送失败（认证）
- 原因：本机 git 凭据没有该云效仓库权限。
- 处理：配置 `publish.token`（+`publish.user`）临时认证；或先在本机 `git clone` 一次该仓库、走 Git Credential Manager 记住凭据。用 `--dry-run-publish` 可先演练。

### localRepo 被中止（有未推送提交/已跟踪改动）
- 原因：为保护你已有的仓库改动。
- 处理：先把该本地仓库处理干净（提交/还原）；确认无误可加 `--force`。

### 上传后论文目录里没有视频
- 原因：`dir`/`filename` 配错，或 push 到了别的分支。
- 处理：看日志里的 `目标: <repo> #<branch> -> <dir>/<file>`；确认 `branch` 与远端一致。

### 仓库很大、clone 很慢
- 处理：配置 `publish.localRepo` 复用已 clone 的本地仓库；或首次用 `--depth` 缓存（脚本默认浅克隆）。



## 8. 仓库号一键制作（make.py / provision）

### 找不到 yx.py / 无法解析仓库号
- 原因：make.py 复用 bishe-lw 的云效客户端。缺 bishe-lw skill 或其 scripts/yx.py 时会报错。
- 处理：确保 C:\Users\<user>\.dsh\skills\bishe-lw\scripts\yx.py 存在，且 ishe-lw\secrets.env 里有 YUNXIAO_PAT。

### 克隆/推送 401/403
- 原因：云效令牌失效或没勾「代码管理 Codeup 读写」。
- 处理：更新 ishe-lw\secrets.env 的 YUNXIAO_PAT；python -I make.py 007 会重新读取。

### provision：未识别后端
- 原因：源码里没有 ackend/requirements.txt（FastAPI）等可识别结构。
- 处理：手动启动系统后加 --url http://127.0.0.1:端口。

### provision：后端启动即退出 / 60 秒未就绪
- 看 <项目号>\provision.log。常见：缺 Python 依赖（pip install -r requirements.txt）、需要 MySQL/Redis、端口被占（脚本会自动换端口）。

### Java / Spring 项目
- 不自动启动。先 mvn spring-boot:run（配好数据库）再用 --url http://127.0.0.1:8080。

### 前端没有 dist
- 脚本会尝试 
pm install + 
pm run build；失败则手动构建 rontend/dist 或用 --url。

### autolesson 枚举到 0 个菜单
- 登录失败或菜单选择器不匹配。确认 --username/--password；非 Element Plus 菜单建议手写 lesson.json 用 --lesson 跳过自动生成。

### 上传后论文目录没有视频
- 看日志里 publish 的目标仓库/目录；确认该仓库有 论文/ 目录、令牌有写权限。
