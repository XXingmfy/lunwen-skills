# webapp-walkthrough 使用手册

> 给一个开发完的 Web 系统，做一套「覆盖全部功能点」的中文使用教学视频：章节化讲解 + 真实操作 + 光标高亮 + 配音字幕，产出 mp4、教学讲稿、功能点清单。

---

## 1. 它到底做什么

```
你的系统 (http://127.0.0.1:xxxx)
      ↓  ego-browser 真实点击 / 输入 / 打开弹窗（按 lesson.json 的教学步骤）
   逐章节逐功能点演示（章节卡 + 光标 + 元素高亮 + 低三分标题）
      ↓  Page.captureScreenshot 定时抽帧（去重）
   录制画面
      ↓  SAPI 中文配音 + ffmpeg 合成（片头/章节卡/字幕/片尾）
   <系统名>_教学_20261121-1330.mp4
```

一次运行产出：

| 产物 | 用途 |
| --- | --- |
| `<系统名>_教学_<时间>.mp4` | 交付/培训用的教学片，带章节卡、光标高亮、配音、烧录字幕 |
| `教学讲稿.md` | 分章节时间轴 + 每步讲解词 + 要点 + 异常，可直接改 |
| `功能点清单.md` | 全部功能点 checklist：功能点 / 页面 / 状态 / 截图 |
| `narration.srt` | 外挂字幕 |
| `shots/*.png` + `steps.jsonl` | 每个功能点截图 + 结构化记录 |

与旧版区别：旧版是"把每个 tab 点一遍"的**演示**；新版是"讲清每个功能怎么用"的**教学**——有章节结构、有操作指引、有结果解读、有要点提示。

---

## 2. 30 秒上手

```bash
# ① 每个系统一个工作目录
mkdir -p ~/ego-walkthrough/my-system
cp ~/.dsh/skills/webapp-walkthrough/templates/config.json        ~/ego-walkthrough/my-system/config.json
cp ~/.dsh/skills/webapp-walkthrough/templates/lesson.example.json ~/ego-walkthrough/my-system/lesson.json

# ② 改 config.json（地址、系统名、成片目录、音色）
# ③ 改 lesson.json（按系统真实页面写章节和功能点）
# ④ 一键出片
python -I ~/.dsh/skills/webapp-walkthrough/scripts/run_all.py ~/ego-walkthrough/my-system
```

成片默认落在 `<outDir>`（未填则 `<projectDir>/video_demo/`，再否则 `D:/video_demo/`）。

也可以直接对我说：**"以 http://127.0.0.1:8777 这个系统为例，做一套覆盖全部功能点的使用教学视频"**，我会读源码路由与页面、写好 `lesson.json`、先跑 1–2 章验证、再跑全量出片。

---

## 3. 配置文件全字段（config.json）

```json
{
  "systemName": "基于BERT的学生评教文本情感分析系统",
  "baseUrl": "http://127.0.0.1:8037",
  "outDir": "D:/work/xxx/video_demo",
  "spaceName": "",
  "login": { "required": false },
  "menuSelector": "aside .el-menu-item, aside a, nav a",
  "tabSelector": ".el-tabs__item, [role=tab]",
  "safeButtons": ["查询", "搜索", "刷新"],
  "denyButtons": ["删除", "退出", "注销"],
  "testQuery": "演示",
  "queryByModule": {},
  "skipPaths": ["/logout"],
  "maxModules": 12,
  "settleMs": 900,
  "humanize": true,
  "expandSubmenus": true,
  "recorder": { "width": 1440, "height": 860, "jpegQuality": 70 },
  "voice": { "engine": "edge", "name": "zh-CN-YunxiNeural", "rate": 1 }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `systemName` | ✅ | 成片文件名、片头标题 |
| `baseUrl` | ✅ | 系统入口 |
| `outDir` | | 成片目录，优先级最高 |
| `projectDir` | | 成片落 `<projectDir>/video_demo/` |
| `spaceName` | | ego TaskSpace 名称前缀（脚本自动加时间戳保证唯一） |
| `login.required` | | 仅旧版自动走查用；教学片把登录写成 `lesson.json` 里的一步即可 |
| `menuSelector` / `tabSelector` | | 自动走查用；Element Plus `.el-menu-item`/`.el-tabs__item`，Ant `.ant-menu-item`/`.ant-tabs-tab` |
| `safeButtons` / `denyButtons` | | 自动走查的按钮白/黑名单，只点查询类 |
| `testQuery` / `queryByModule` | | 自动走查填值 |
| `skipPaths` / `maxModules` | | 自动走查过滤 |
| `settleMs` | | 每次导航/操作后稳定等待，默认 900；页面慢加到 1500 |
| `humanize` | | 是否逐字输入 |
| `expandSubmenus` | | 发现前展开折叠菜单，默认 true |
| `recorder.width/height` | | 拍摄视口 = 成片分辨率 |
| `recorder.jpegQuality` | | 68–75 均衡 |
| `voice.engine/name/rate` | | 配音引擎与音色，见下方 §3.1 |

---

### 3.1 配音音色

| engine | 示例 | 特点 |
| --- | --- | --- |
| `edge`（推荐） | `{"engine":"edge","name":"zh-CN-YunxiNeural","rate":1}` | 微软神经音色，自然，需联网（edge-tts 已装） |
| `sapi` | `{"engine":"sapi","name":"Microsoft Huihui Desktop","rate":0}` | 离线 SAPI，机械感较强 |
| 自动 | 只填 `name` | `zh-CN-` 开头走 edge，否则 sapi |

常用中文神经音色（`name`）：

- 女声：`zh-CN-XiaoxiaoNeural`（晓晓·温暖）、`zh-CN-XiaoyiNeural`（晓伊·活泼）、`zh-CN-liaoning-XiaobeiNeural`（东北话）、`zh-CN-shaanxi-XiaoniNeural`（陕西话）
- 男声：`zh-CN-YunxiNeural`（云希·阳光）、`zh-CN-YunyangNeural`（云扬·沉稳专业）、`zh-CN-YunjianNeural`（云健·有激情）、`zh-CN-YunxiaNeural`（云夏·卡通可爱）

可选 `volume`/`pitch`/`edgeRate`。edge 失败自动回退 SAPI。

> 自己的声音：①把录音按台词分段发来，用外部音频轨替换（100% 真声）；②接入声音克隆 TTS（CosyVoice / GPT-SoVITS / 火山 / MiniMax / Azure）替换 `synth`。内置引擎不能"克隆一段录音"。

### 3.2 上传到云效（与论文同目录）

出片后自动把成片推到云效 Codeup 仓库指定目录，默认 `论文/`（与论文同目录）。配置 `config.json` 的 `publish`：

```json
"publish": {
  "enabled": true,
  "repo": "https://example-cn-beijing.devops.aliyuncs.com/codeup/bishe007.git",
  "branch": "main",
  "dir": "论文",
  "subdir": "",
  "filename": "{system}_教学视频_{date}.mp4",
  "includeDocs": false,
  "localRepo": "",
  "commit": "docs(演示视频): 新增《{system}》教学视频（{date}）"
}
```

| 字段 | 说明 |
| --- | --- |
| `enabled` | true 时 run_all 出片后自动上传；也可命令行 `--publish` 强制、`--no-publish` 跳过 |
| `repo` / `branch` | 目标云效仓库与分支 |
| `dir` / `subdir` | 目标目录，默认 `论文`；可加 `subdir` 放子目录 |
| `filename` | 文件名模板，支持 `{system}` `{date}` |
| `includeDocs` | 是否连 `教学讲稿.md`/`功能点清单.md` 一起传 |
| `localRepo` | 可选，复用已有本地 clone（免重复克隆）；有未推送提交/已跟踪改动会中止（`--force` 覆盖） |
| `commit` | 提交信息模板 |
| `token`/`user` | 可选，临时认证用，不落盘；默认用本机 Git Credential Manager |

也可单独执行：`python -I scripts/publish.py <工作目录> --video <成片.mp4> [--dry-run]`。

### 3.3 一键：只给云效仓库号（make.py）

和 bishe-lw 一样，给一个云效仓库号就能出片：

```bash
python -I scripts/make.py 007
```

自动链路：解析仓库号（复用 bishe-lw 的 `config.yaml` + `secrets.env` 令牌）→ 克隆到
`D:\Tools_Home\DeepseekHarness_Load\video\<项目号>\repo` → 自动启动系统 → 生成教学脚本
（没给就用 autolesson 自动枚举菜单）→ 录制/配音/合成 → 上传回云效（默认 `论文/` 目录）。

| 参数 | 说明 |
| --- | --- |
| `--lesson <file>` | 指定教学脚本，质量更高 |
| `--url <addr>` | 系统已在运行，跳过自动启动 |
| `--voice <name>` | 音色，默认 `zh-CN-XiaoxiaoNeural` |
| `--no-publish` | 只本地产出 |
| `--workdir-root <dir>` | 本地根目录 |
| `--username/--password` | 自动登录账号 |

本地目录固定：`video\<项目号>\{repo, config.json, lesson.json, video_demo, run, provision.log}`。

> 自动启动目前覆盖 Python(FastAPI/Flask)+SQLite 且带 `frontend/dist` 的项目；
> Java/Spring 或前端需现场构建的，请先自行启动并用 `--url` 指定地址。

## 4. 教学脚本 lesson.json 详解

教学片的核心。结构：`chapters[] → steps[]`。

### 4.1 顶层

```json
{
  "systemName": "…",
  "baseUrl": "http://127.0.0.1:8037",
  "viewport": { "width": 1440, "height": 860 },
  "cardMs": 2000,
  "intro": "开场白",
  "outro": "收尾语",
  "chapters": [ ... ]
}
```

### 4.2 章节与步骤

```json
{
  "title": "单条情感分析",
  "summary": "核心能力：对一条评教文本做三档情感判定与可解释归因。",
  "steps": [
    {
      "title": "单条分析 / 归因",
      "url": "/analysis/text",
      "narration": "输入评语后点分析情感，系统给出正面/中性/负面判定和证据词；再点遮挡法归因定位关键词。",
      "tips": "规则通道可无缝替换为 BERT 权重",
      "actions": [
        { "type": "fill", "selector": "textarea", "value": "老师讲课非常生动，重点突出。" },
        { "type": "click", "text": "分析情感", "ms": 1400 },
        { "type": "click", "text": "遮挡法归因", "ms": 1400 }
      ],
      "highlight": { "selector": ".card" },
      "holdMs": 2000
    }
  ]
}
```

### 4.3 actions 动作表

| type | 参数 | 作用 |
| --- | --- | --- |
| `fill` | `selector`（省略=第一个可见输入框）、`value` | 清空后逐字输入 |
| `click` | `text` 或 `selector`；`findSelector`、`label`、`ms` | 点击并画光标/高亮/涟漪 |
| `goto` | `url`、`ms` | 路由跳转 |
| `press` | `key` | 按键 |
| `hover` | `text`/`selector` | 悬停 |
| `scroll` | `dy` | 滚动 |
| `wait` | `ms` | 等待接口/动画 |

> 多行表格里的按钮：`"selector": ".el-table__body .el-button >> nth=0"` + `"findSelector": ".el-table__body .el-button"`。

### 4.4 写脚本的三条经验

1. **每个功能点一步**：按钮、表单、查询、弹窗、图表都要有对应步骤，才算"覆盖全部功能点"。
2. **narration 口语化、一步一重点**：每句 30–60 字，讲"这是什么 → 怎么操作 → 结果怎么看 → 注意什么"。
3. **先小后大**：先写 1–2 章跑通（验证登录与选择器），再补全所有章节。

---

## 5. 一次标准流程

### 5.1 先摸清系统功能点

读源码 `router`（有哪些路由/页面）、菜单组件（有哪些菜单/角色可见）、各页面 vue（有哪些按钮、表单、弹窗）。得到"章节 → 功能点"清单。

### 5.2 写 config.json + lesson.json

见第 3、4 节。

### 5.3 验证一小段

先把 `lesson.json` 只留第 1 章（或前两个功能点），跑一次看画面、光标、高亮、字幕是否正常。

### 5.4 跑全量

```bash
python -I scripts/run_all.py ~/ego-walkthrough/my-system
```

日志实时打印每个功能点耗时与异常数。

### 5.5 看产物、按需精修

- 看 `run/功能点清单.md`：哪些功能点标了 ❌，看 `run/shots/` 对应截图，改 `lesson.json` 的选择器后重跑。
- 想改某句配音：写 `narration.json`（键=步骤序号），`--narrate-only --script narration.json` 只重做讲解与合成，不重录。

---

## 6. 常见场景配方

| 场景 | 做法 |
| --- | --- |
| Element Plus 后台 | 选择器用 `.el-menu-item`、`.el-tabs__item`；弹窗 `.el-dialog`、抽屉 `.el-drawer` |
| Ant Design Pro | `.ant-menu-item`、`.ant-tabs-tab` |
| 需要登录 | 把登录写成一章一步，填账号密码点登录；或旧版 `login.required` |
| 要覆盖学生/教师/管理员多角色 | 每个角色一套 `lesson.json` 各出一条片；或用不同账号登录的步骤 |
| 只要视频不要配音 | 跳过 narrate，直接 `assemble.py`；或 `voice.name` 置空 |
| 只要截图巡检 | 跑完 `run.mjs` 就停，看 `run/shots/` 与 `steps.jsonl` |
| 系统在 Docker/远程 | `baseUrl` 指向可达地址即可；ego 同机运行 |

---

## 7. 输出规格

- 编码：H.264 / yuv420p / 30fps / AAC 22050Hz 单声道
- 分辨率：`recorder.width × recorder.height`
- 结构：片头卡 →（章节卡 → 该章各功能点画面）… → 片尾卡
- 命名：`<系统名>_教学_<yyyyMMdd-HHmm>.mp4`

---

## 8. 能力边界（先说清）

1. **帧率约 2–4 fps**（captureScreenshot 轮询上限）。静态页面看不出差别；快速动画会略顿。靠"定格 + 配音"补足节奏。
2. **画的是页面，不是浏览器窗口**（无地址栏，反而更干净）。
3. **教学层是 DOM 覆盖层**：整页导航会清掉，脚本每步自动重新注入；被原样录进画面。
4. **只做"安全操作"**：演示查询、打开详情/弹窗、填测试值。删除/支付类需要你自己加并准备清理方案。
5. **配音是离线 TTS**，机械感明显；要真人效果就替换 `narration.wav` 为自己的录音再 `assemble.py`。
6. **选择器依赖页面结构**：自定义组件可能对不上，改 `lesson.json` 的 `selector`/`findSelector` 即可。

---

## 9. 出问题看哪

| 现象 | 先看 |
| --- | --- |
| 画面只有几帧 / 不动 | troubleshooting §2（screencast 已废弃，改 captureScreenshot） |
| 某功能点被标异常 | 看 `run/shots/` 该步截图 + `steps.jsonl`，改选择器 |
| 点击报 `matched 2 elements` | 用 `>> nth=0` 或更精确 selector |
| 没声音 | SAPI 音色（`voice.name` 留空自动选 zh-CN） |
| 字幕太大/不显示中文 | `assemble.py` 的 FontSize 与 `msyh.ttc` |
| 自动走查模块为 0 | `menuSelector` 不对，或菜单在 iframe 里 |

完整排障：`~/.dsh/skills/webapp-walkthrough/references/troubleshooting.md`

---

## 10. 目录速查

```
~/.dsh/skills/webapp-walkthrough/
├── SKILL.md                      # 给 agent 读的执行规范
├── MANUAL.md                     # 本手册
├── templates/
│   ├── config.json               # 配置模板
│   └── lesson.example.json       # 教学脚本模板
├── references/troubleshooting.md
└── scripts/
    ├── run_all.py                # 一键编排（推荐入口，自动定位 ego 版本）
    ├── discover.mjs              # 自动走查：枚举模块/选项卡 → plan.json
    ├── run.mjs                   # 教学录制（lesson.json）+ 抽帧 + 断言 → steps.jsonl
    ├── narrate.py                # 教学讲稿 / 功能点清单 / 字幕 / 配音音轨
    ├── assemble.py               # 合成 mp4（片头/章节卡/字幕/片尾）
    └── publish.py                # 上传成片到云效（默认与论文同目录）
```
