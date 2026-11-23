---
name: webapp-walkthrough
description: 把一个已开发完的 Web 系统，一键录制成「覆盖全部功能点的中文使用教学视频」：真实操作每个模块/功能点，带章节卡、光标与元素高亮、教学式旁白、烧录字幕，产出成片 mp4 + 教学讲稿 + 功能点清单 + 每步截图。也保留旧版「逐选项卡自动走查」模式。当用户说"给系统做一套使用教学视频/操作教程"、"把所有功能点讲一遍录下来"、"以XX系统为例子做个教学片"、"做完系统帮我跑一遍并录像"、"给每个模块每个 tab 点一遍"、"录制操作演示并配音"时使用。
---

# webapp-walkthrough — 系统使用教学视频（全部功能点）

把"开发完的系统"变成"可直接给用户/学生/评审看的使用教程"。

两种模式：

| 模式 | 输入 | 产物 | 适用 |
| --- | --- | --- | --- |
| **教学视频（推荐，主模式）** | `lesson.json` 教学脚本 | 章节化教学片 + 教学讲稿 + 功能点清单 | 要"讲清每个功能怎么用"、覆盖全部功能点 |
| 自动走查（兼容旧版） | 自动发现 `plan.json` | 逐选项卡演示片 + 讲解稿 | 只想快速扫一遍每个页面有没有白屏/报错 |

底层：`ego-browser`（ego lite）真实点击/输入 → `Page.captureScreenshot` 定时抽帧 → Windows SAPI 中文配音 → ffmpeg 合成（片头/章节卡/字幕/片尾）。教学层（章节卡、光标、元素高亮、点击涟漪、低三分标题条）用注入的 DOM 覆盖层实现，被原样录进画面。

## 何时使用

- 系统上线/交付，需要一份"覆盖全部功能点"的用户使用教学视频
- 需要给学生/客户/评审看"每个功能怎么操作、结果怎么读"
- 顺带想发现点了会 500、页面白屏这类低级问题（产物里的功能点清单会标异常）

不适用：需要精确像素级动效（抽帧约 2–4 fps）；录制桌面/其他应用。

## 前置条件

| 依赖 | 检查 | 缺失处理 |
| --- | --- | --- |
| ego-browser | 脚本自动扫描 `C:\Program Files\Citro Labs\ego lite\Application\*\ego-browser.exe` 取最高版本 | 按 `~/.agents/skills/ego-browser/references/install.md` 安装 |
| ffmpeg | `ffmpeg -version` 或 winget 包路径 | `winget install Gyan.FFmpeg` |
| Python 3.10+ | `python --version` | 系统已有 |
| numpy / pillow | `python -I -c "import numpy, PIL"` | `pip install numpy pillow` |
| 中文字音 | `edge_tts` 已装且可联网（首选）；或 SAPI 含 `Microsoft Huihui Desktop` | 无 edge 则回退 SAPI 任一 zh-CN 音色 |

被录制系统必须本地可访问（`http://127.0.0.1:xxxx`），并已初始化好演示数据；需要登录的，账号密码写进 `lesson.json` 的登录步骤里（教学片通常会**把登录过程本身也录进去**）。

## 目录约定

```
~/ego-walkthrough/
├── active.txt                 # 指向当前工作目录（run_all.py 自动写）
└── <项目>/
    ├── config.json            # 基础配置（系统名、地址、视口、音色…）
    ├── lesson.json            # 教学脚本（主模式的核心输入）
    ├── plan.json              # 自动发现生成（仅自动走查模式用）
    └── run/                   # 本次运行产物
        ├── frames/            # 抽帧 + index.json
        ├── shots/             # 每个功能点一张截图
        ├── steps.jsonl        # 步骤流水（讲解与剪辑唯一数据源）
        ├── meta.json
        ├── 教学讲稿.md         # 分章节时间轴 + 讲解词 + 要点 + 异常
        ├── 功能点清单.md       # 全部功能点 checklist（含状态、截图）
        ├── narration.wav / narration.srt / timeline.json
        └── concat.txt
```

## 快速开始（教学视频）

### 1. 写 config.json

从 `templates/config.json` 复制，最少改：

```json
{
  "systemName": "基于BERT的学生评教文本情感分析系统",
  "baseUrl": "http://127.0.0.1:8037",
  "outDir": "D:/work/xxx/video_demo",
  "recorder": { "width": 1440, "height": 860, "jpegQuality": 70 },
  "voice": { "name": "Microsoft Huihui Desktop", "rate": 1 }
}
```

- `outDir`：成片目录（优先）；不填回落 `<projectDir>/video_demo/`，再回落 `D:/video_demo/`。
- `recorder`：拍摄视口，决定成片分辨率；`jpegQuality` 68–75 较均衡。

### 2. 写 lesson.json（教学脚本）

这是教学视频的灵魂：**按"章节 → 功能点"组织**，每一步写清"这步教什么、怎么操作、结果怎么看、有什么要点"。参考 `templates/lesson.example.json`。

```json
{
  "systemName": "…",
  "baseUrl": "http://127.0.0.1:8037",
  "cardMs": 2000,
  "intro": "开场白，一句话说明本片覆盖什么。",
  "outro": "收尾语。",
  "chapters": [
    {
      "title": "登录与工作台",
      "summary": "本章讲什么（会显示在章节卡上）。",
      "steps": [
        {
          "title": "账号登录",
          "url": "/login",
          "narration": "这一句就是配音，也是字幕。口语化、一次讲清一个功能点。",
          "tips": "可选，低三分里显示的要点小字",
          "actions": [
            { "type": "fill", "selector": "input[placeholder=\"用户名 / 学号\"]", "value": "admin" },
            { "type": "fill", "selector": "input[placeholder=\"密码\"]", "value": "123456" },
            { "type": "click", "selector": "button.el-button", "label": "点击登录" },
            { "type": "wait", "ms": 1500 }
          ],
          "holdMs": 1400
        }
      ]
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `cardMs` | | 章节卡停留毫秒，默认 2000 |
| `intro` / `outro` | | 片头/片尾旁白；不填自动生成 |
| `chapters[].title` | ✅ | 章节名（章节卡、低三分、讲稿都用它） |
| `chapters[].summary` | ✅ | 本章导语（章节卡的副标题 + 该章节的旁白） |
| `chapters[].card` | | 设 `false` 可跳过本草章节卡 |
| `steps[].title` | ✅ | 功能点名（低三分主标题 + 讲稿/清单行名） |
| `steps[].url` | | 该功能点页面路由；会先导航再操作 |
| `steps[].narration` | ✅ | 这一步的讲解词（配音 + 字幕） |
| `steps[].tips` | | 低三分里的黄色要点小字 |
| `steps[].actions` | | 操作序列（见下表），空则只展示页面 |
| `steps[].highlight` | | 结束后高亮的目标：`{ "selector": "..." }` 或 `{ "text": "..." }` |
| `steps[].holdMs` | | 操作完成后额外停留毫秒，默认 = `settleMs` |
| `steps[].settleMs` | | 本步导航后的稳定等待覆盖值 |

`actions` 支持的 `type`：

| type | 参数 | 作用 |
| --- | --- | --- |
| `fill` | `selector`（或省略=第一个可见输入框）、`value` | 清空后逐字输入（≤44 字时可见打字过程） |
| `click` | `text` 或 `selector`；`findSelector`（用于高亮定位）；`label`；`ms` | 点击，并画光标/高亮/涟漪 |
| `goto` | `url`、`ms` | 路由跳转 |
| `press` | `key` | 键盘按键（如 `Enter`） |
| `hover` | `text`/`selector` | 悬停 |
| `scroll` | `dy` | 页面滚动 |
| `wait` | `ms` | 纯等待（用于等接口/动画） |

> 点击已有多行的表格按钮时用 `selector: ".el-table__body .el-button >> nth=0"`，再用 `findSelector: ".el-table__body .el-button"` 指定高亮目标，避免"匹配到多个元素"。

### 3. 一键出片

```bash
python -I scripts/run_all.py ~/ego-walkthrough/<项目>
```

检测到工作目录里有 `lesson.json` 就走教学视频模式（跳过自动发现）。四段：录制 → 讲解/字幕/讲稿 → 合成，日志实时打印。

也可以 `--lesson path/to/lesson.json` 显式指定（会被复制到工作目录）。

### 4. 精修（可选）

想改某一步的配音而不重录，写一份 `narration.json`（键为步骤序号）后只重跑讲解与合成：

```bash
python -I scripts/run_all.py ~/ego-walkthrough/<项目> --narrate-only --script narration.json
```

## 配音音色（voice）

配音引擎可切换，配置在 `config.json` 的 `voice`：

| engine | 示例 | 说明 |
| --- | --- | --- |
| `edge`（推荐） | `{"engine":"edge","name":"zh-CN-YunxiNeural","rate":1}` | 微软神经音色，自然度高，需联网（edge-tts） |
| `sapi` | `{"engine":"sapi","name":"Microsoft Huihui Desktop","rate":0}` | 离线 Windows SAPI，机械感较强 |
| 自动 | 只填 `name` | `name` 以 `zh-CN-` 开头走 edge，否则走 sapi |

常用中文神经音色（写在 `name`）：

- 女声：`zh-CN-XiaoxiaoNeural`（晓晓·温暖）、`zh-CN-XiaoyiNeural`（晓伊·活泼）、`zh-CN-liaoning-XiaobeiNeural`（东北话·幽默）、`zh-CN-shaanxi-XiaoniNeural`（陕西话·明亮）
- 男声：`zh-CN-YunxiNeural`（云希·阳光）、`zh-CN-YunyangNeural`（云扬·沉稳专业）、`zh-CN-YunjianNeural`（云健·有激情）、`zh-CN-YunxiaNeural`（云夏·卡通可爱）

可选 `volume`（如 `"+0%"`）、`pitch`（如 `"+0Hz"`）、`edgeRate`（如 `"+10%"`，优先于 `rate`）。edge 合成失败（断网/未装）会自动回退 SAPI 离线音色，不中断出片。

> 想用**自己的真实声音**：①把自己的录音按台词分段发来，脚本用外部音频轨替换（100% 真声）；②接入声音克隆 TTS（CosyVoice / GPT-SoVITS / 火山 / MiniMax / Azure），替换 `synth` 即可。内置引擎不含"克隆一段录音生成任意台词"的能力。

## 上传到云效（与论文同目录）

出片后可自动把成片上传到云效 Codeup 仓库的指定目录，**默认与论文存放同一目录**（`论文/`）。在 `config.json` 配置 `publish`：

```json
"publish": {
  "enabled": true,
  "repo": "https://example-cn-beijing.devops.aliyuncs.com/codeup/bishe007.git",
  "branch": "main",
  "dir": "论文",
  "subdir": "",
  "filename": "{system}_教学视频_{date}.mp4",
  "includeDocs": false,
  "localRepo": "D:/已有clone路径（可选）",
  "commit": "docs(演示视频): 新增《{system}》教学视频（{date}）"
}
```

- 触发：`publish.enabled=true` 或命令行 `--publish`；`--no-publish` 跳过；`--dry-run-publish` 只演练。
- `dir` 默认 `论文`（与论文同目录）；也可 `"dir":"论文","subdir":"系统演示视频"` 放子目录。
- 凭据：复用本机 git 凭据（Git Credential Manager）；也可配 `publish.token`(+`user`) 临时认证，不落盘。
- 安全：只 `git add` 目标目录下的目标文件；不 force push；复用 `localRepo` 时若有未推送提交/已跟踪改动会中止（`--force` 覆盖）。
- 单独运行：`python -I scripts/publish.py <工作目录> --video <成片.mp4> [--dry-run]`。

## 一键：只给云效仓库号（像 bishe-lw）

```bash
python -I scripts/make.py 007
```

自动完成：解析仓库号（复用 bishe-lw 的云效配置与令牌）→ 克隆到 `D:\Tools_Home\DeepseekHarness_Load\video\<项目号>\repo` → 自动启动系统 → 生成教学脚本（未提供则自动枚举菜单）→ 录制/配音/合成 → 上传回云效（默认与论文同目录 `论文/`）。

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--lesson lesson.json` | 指定教学脚本（质量更高；不指定则 autolesson 按菜单自动生成） |
| `--url http://127.0.0.1:8080` | 系统已运行时跳过自动启动 |
| `--voice zh-CN-YunxiNeural` | 配音音色（默认晓晓） |
| `--no-publish` | 只在本地产出，不上传 |
| `--workdir-root <目录>` | 本地根目录（默认 `D:\Tools_Home\DeepseekHarness_Load\video`） |
| `--username/--password` | 自动登录账号（默认 admin/123456） |

本地目录固定为 `D:\Tools_Home\DeepseekHarness_Load\video\<项目号>\`：`repo\`（克隆）、`config.json`、`lesson.json`、`video_demo\*.mp4`、`run\`（中间产物）。

> 自动启动支持 Python(FastAPI/Flask)+SQLite、且带 `frontend/dist` 的毕设项目；Java/Spring 或前端需现构建的，先用 `--url` 指定已运行地址（详见 troubleshooting §8）。

## 让 agent 帮你写 lesson.json（推荐工作流）

1. 先读系统源码里的**路由表 / 菜单组件 / 各页面 vue**，列出"模块 → 页面 → 功能点（按钮、表单、查询、弹窗、图表）"。
2. 按"章节 → 功能点"落成 `lesson.json`，**确保每个功能点都有一步**；每步 `narration` 写"这是什么 + 怎么操作 + 结果怎么看"。
3. 先只跑一小段（1–2 章）验证选择器与登录，再跑全量。

这样产出的不是"把每个 tab 点一遍"的演示，而是"讲清每个功能怎么用"的教程。

## 自动走查模式（兼容旧版）

没有 `lesson.json` 时退回旧逻辑：先发现计划、人工核对，再整条跑。

```bash
python -I scripts/run_all.py <项目> --discover-only   # 只生成 plan.json，人工核对
python -I scripts/run_all.py <项目>                    # 未放 lesson.json 时自动走查
```

- `menuSelector`：侧边栏选择器。Element Plus `.el-menu-item`；Ant `.ant-menu-item`；原生 `aside a, nav a`。
- `expandSubmenus`（默认 true）：发现前自动展开折叠式子菜单，避免漏掉二级菜单。
- 只点 `safeButtons` 白名单（查询/刷新类），绝不点删除/提交/支付。

## 录制原理与硬约束（ego lite 0.6.3.17 实测）

- **抽帧走 `page.cdp("Page.captureScreenshot", {format:"jpeg"})` 定时轮询**，按画面变化去重后存 jpg，并记录时间戳。约 2–4 fps，静态页只在变化时出帧，成片靠"定格 + 配音"补节奏。
- **不要再用 `Page.startScreencast` + `Page.screencastFrameAck`**：新版 ego 的 `Page.cdp` 禁止在 params 里带 `sessionId`，而 ack 又必须带，导致只出 1–3 帧就卡死（已实测）。captureScreenshot 路线稳定可用。
- 章节卡/光标/高亮/低三分/涟漪都是注入 `document.body` 的 `#wt-ui` 覆盖层（`position:fixed; z-index` 极高、`pointer-events:none`）。**页面整页导航（goto）会清掉覆盖层**，所以脚本在每次导航后都会重新注入。
- 视口用 `Emulation.setDeviceMetricsOverride` 固定为 `recorder.width × recorder.height`，避免帧尺寸不一致。
- 定位一律用 `data-wt` 临时标记或语义选择器，**绝不改目标元素的 `id`**（会破坏页面自身 `getElementById`，实测把查询框值丢了）。
- 录制状态（登录 token）存在浏览器同源 localStorage，后续 `goto` 仍保持登录。

## 输出产物

| 文件 | 说明 |
| --- | --- |
| `<outDir>/<系统名>_教学_<yyyyMMdd-HHmm>.mp4` | 成片：片头卡 + 章节卡 + 逐功能点画面（带光标/高亮/低三分）+ 配音 + 烧录字幕 + 片尾卡 |
| `run/教学讲稿.md` | 分章节时间轴 + 每步讲解词 + 要点 + 异常列，可直接改 |
| `run/功能点清单.md` | 全部功能点 checklist：功能点 / 页面 / 状态（✅正常/❌异常）/ 截图 |
| `run/narration.srt` | 外挂字幕 |
| `run/shots/*.png` | 每个功能点一张截图 |
| `run/steps.jsonl` | 结构化流水（含章节、功能点、操作、异常判定） |

## 输出规格

- 视频：H.264 / yuv420p / 30fps / AAC 单声道，分辨率 = `recorder.width × recorder.height`
- 结构：片头卡 → （章节卡 → 该章各功能点）… → 片尾卡
- 命名：`<系统名>_教学_<yyyyMMdd-HHmm>.mp4`

## 常见失败

见 `references/troubleshooting.md`。最常遇到：

1. 画面只有几帧/不动 → 用了旧版 screencast 路径，或抽帧间隔过大；本版已改 captureScreenshot 轮询。
2. `plan.json` 模块数为 0（自动走查）→ `menuSelector` 不对，或菜单在 iframe 里。
3. 点击报 `matched 2 elements` → 加 `>> nth=0` 或换更精确的 `selector`。
4. 没有声音 → SAPI 音色名不匹配；`voice.name` 留空用默认 zh-CN。
5. 教学脚本某步选择器找不到 → 该步会记一条异常并继续；看 `run/shots/` 与 `steps.jsonl` 定位后改 `lesson.json` 重跑。
