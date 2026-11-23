# lunwen-skills · 论文生产技能合集

一套面向本科毕业论文（毕设）生产与配套交付的 Agent Skills 合集，覆盖「架构图 → 使用教学视频 → 论文成文 → 学校格式排版 / 查重 / 降 AIGC / 上传」的完整链路。

本仓库为技能包（Skill）整理版，每个子目录是一个可独立安装的技能，目录内 `SKILL.md` 为该技能的完整使用说明。

## 技能一览

| 目录 | 技能 | 作用 |
| --- | --- | --- |
| [`architecture-diagram-pptx/`](architecture-diagram-pptx/SKILL.md) | architecture-diagram-pptx | 用 PowerPoint 原生可编辑元素制作系统架构图 / 分层图 / 拓扑图 / 部署图 / 数据流图，输出同名 `.pptx` 源文件与长边 ≥ 2000px 的 `.png` 预览。 |
| [`webapp-walkthrough/`](webapp-walkthrough/SKILL.md) | webapp-walkthrough | 把已开发完的 Web 系统一键录制成「覆盖全部功能点的中文使用教学视频」，含章节卡、光标高亮、教学旁白与字幕。 |
| [`bishe-lw/`](bishe-lw/SKILL.md) | bishe-lw | 由一个云效代码库号，自动拉取任务书 / 开题报告 / 源码，匹配学校格式档案，调用写作引擎成文出图，过 AIGC 检测与查重后，按「学号_姓名_专业_题目」命名并推回仓库论文目录。 |
| [`hbks-lw-skill/`](hbks-lw-skill/SKILL.md) | hbks-lw-skill | 河北科技师范学院（及同类高校）本科毕业论文 .docx 生产流水线：源码证据 → 硬性大纲 → 逐章成文 → Visio 图 → 降 AIGC → 质检 → docx/PDF 双版本交付。 |

## 安装 / 使用

这些技能面向支持 Skill 的 Agent 环境（例如 DSH / Claude 类工具）。把对应目录放入你的技能目录即可，例如：

```text
~/.dsh/skills/
├── architecture-diagram-pptx/
├── bishe-lw/
├── hbks-lw-skill/
└── webapp-walkthrough/
```

随后在对话中按技能描述触发（如「画架构图」「给系统做教学视频」「写毕业论文」），或显式调用技能。详见各目录下的 `SKILL.md`。

## 依赖提示

- `architecture-diagram-pptx`：需要 Python + python-pptx，导出 PNG 用本机 Microsoft PowerPoint（COM）。
- `webapp-walkthrough`：需要 ego-browser、ffmpeg、Python（numpy / pillow），配音可用 edge-tts 或 Windows SAPI。
- `bishe-lw`：需要云效（阿里云 Codeup）访问令牌、腾讯朱雀 AIGC 检测 Key；令牌请放在本机 `secrets.env`（本仓库已忽略，不会入库）。
- `hbks-lw-skill`：需要 Windows + Microsoft Word / Visio 的 COM 自动化环境。

## 配置与密钥

本仓库**不包含任何密钥**。各技能运行所需的令牌 / Key 请自行在本机配置（如 `bishe-lw/secrets.env` 或环境变量），该文件已被 `.gitignore` 排除，请勿提交。

## 免责声明

技能中的示例路径、域名、项目 ID、账号均为占位符（如 `<user>`、`your_yunxiao_user`），使用前请按本机与自有账号替换。论文写作、AIGC 检测与查重结果仅供参考，不代表任何检测器必然通过；最终以作者可辩护的事实与学校正式要求为准。
