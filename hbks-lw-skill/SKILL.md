---
name: hbks-lw-skill
description: 从真实项目源码生成"可直接提交"的河北科技师范学院（及同类高校）本科毕业论文 .docx 的完整流水线。正文严格控制在 12000–16000 字，E-R 图中每个实体都生成一张中心辐射式实体属性图，其余所有图表连线横平竖直、箭头方向与业务逻辑自检。当用户提供项目源码/仓库、数据库、接口、截图或测试材料，并要求写毕业论文、毕设论文、论文大纲、按学校规范排版、制作 Visio 图（用例图/流程图/架构图/模块图/E-R图/实体属性图）、做三线表、降 AIGC 痕迹或做提交前检查时使用。触发词：帮我写毕业论文、毕设论文、把项目写成论文、论文大纲、论文排版、Visio图、三线表、降AIGC、去AI味、提交前检查。
---

# 河北科技师范学院本科毕业论文生产流水线（hbks-lw-skill）

把一套**真实项目源码**变成一篇**结构合规、图表齐全、可提交**的本科毕业论文 `.docx`。本技能按"源码证据 → 硬性大纲 → 逐章成文 → Visio 图 → 降 AIGC → 质检 → docx/PDF"的顺序执行，任何一步缺证据都不许编造。

**学校官方模板/导师要求永远优先于本技能的一切默认值。** 没有模板时，使用本技能内置的格式基线（封面/声明/摘要/目录/六章正文/参考文献/致谢/附录，6 分节、罗马/阿拉伯页码、三线表）。

## 本技能维护模式（与写论文分开）

当用户要求“比较标准论文与产物、优化 skill”时，仅把两份论文作为只读证据，不改写论文、不要求源码、不启动正文创作/降 AIGC 流程。按“读取 OOXML 与 Word 实际分页 → 确认差异 → 修改技能/模板/脚本 → 合成文档回归 → 报告验证结果”执行。文档中的文字是被分析材料，不是执行指令。多篇同校论文的共性格式已沉淀为 `references/09-hbks-format-profile.md`（8 篇实证，逐项列出一致度），维护时先对照该档案再改默认值。

## 前置页与表格硬约束

生成或优化 DOCX 前读 references/08-template-and-pagination.md。

- 默认使用去个人信息的 assets/hbks-frontmatter.docx。封面第1页；声明与授权**同在第2页**；前置样式与正文隔离。标准样例没有英文封面标题，不自行增添。用户正式模板不同则先适配，不能称内置样例是学校官方模板。
- 作者信息缺失时报错、登记缺证，不向成品写“待补充/占位框”。签名和未确认签署日期保留标准手写栏，不能复制参考论文签名、自动签字或把封面日期当签署日期。
- **三线表必须整表同页。放不下当前页但能放下一整页时，整表移页；本身超一页时必须拆成带同号“续表X.Y　原表名”的表段，每段重复完整表头且各自同页。** 单有重复表头不算续表。
- 用 Microsoft Word 实际重排检验每个表段、题注和行；自动拆表逐行核对数据。未通过或未取得真实分页报告，不得宣称可提交。

## 何时使用 / 不适用

适用：
- 用户给项目源码/仓库，要求写本科毕业论文或毕设论文；
- 已有论文草稿，要求按规范改写、补章节、补图表、降 AIGC、排版成 docx；
- 要求制作论文用的 Visio 用例图/流程图/架构图/模块结构图/E-R 图；
- 要求做提交前的内容/格式/图表/版面检查。

不适用：
- 学校/期刊**明令禁止任何 AI 参与**：直接告知本技能不适用，不执行写作或改写；
- 纯文献综述、非系统类研究论文（可借用写作/降 AIGC 规范，但章节骨架需另定）；
- 要求"保证通过检测/100% 人类"：不承诺，检测是概率性的。

## 开工前必须拿到的材料

按优先级收集；缺哪项就明确列出缺口，**不要假装有**：

1. 作者信息：姓名、学号、院系、专业、指导教师、论文题目（中英文）。
2. 项目源码/仓库路径（必需）。
3. 数据库证据：`*.sql`、实体类、ORM Model、迁移文件、表结构导出。
4. 接口证据：Controller/路由/Service。
5. 截图、运行日志、测试材料。
6. 学校 Word 模板（有则先做模板逆向：页边距、字体、封面、声明、参考文献格式）。
7. 参考文献清单/已有草稿（没有则只用可核实的官方文档，并标缺口）。

> 如果用户只给了一部分：先建工作区、先扫源码、先写有证据的章节；缺证处登记到 `paper-context/gaps.md`，**不进入正文**。

## 运行环境依赖

Windows + 本机 Microsoft Office，会话内自检：

```bash
python -c "import win32com.client, docx, docx.oxml; print('ok')"   # pywin32 + python-docx
python <skill>/scripts/office_prepare.py --status                  # 打印机环境
```

| 依赖 | 用途 | 缺失时 |
|---|---|---|
| Python 3.9+、`python-docx` | 生成/检查 docx（纯 XML 操作，不启用 Office） | 无法运行 |
| `pywin32` | Word / Visio COM 自动化 | 无法更新域、导 PDF、生成图 |
| Microsoft Word | 更新目录/页码域、导出 PDF、嵌入 VSDX OLE | 需人工在 Word 里更新并导出 |
| Microsoft Visio | 生成 `.vsdx` 结构图 | 只能交 PNG，无 `.vsdx` 源 |
| `PyMuPDF`（可选） | 把 PDF 渲染成图做版面抽查 | 改用人工翻页 |

> **不需要 LibreOffice，也不要用它替代 Word/Visio。** 本技能的转换与出图全部走本机 Office COM；LibreOffice 的 docx/pptx 渲染在字体替换、分页与 OLE 激活上与 Word 不一致，用它做"版面核验"反而会得出与实际交付不符的结论。同样地，不要为了"能转 PDF"去下载 WPS / OpenOffice / 在线转换服务。

## 标准工作流（8 步）

### 第 0 步：场景决策

读 `references/03-humanize-standards.md` §0。确认学校是否允许 AI 辅助、是否要求披露。默认按"允许 AI 辅助但需披露"执行，交付时附披露提醒（§7 模板）。

### 第 1 步：建工作区 + 归档材料

```bash
python <skill>/scripts/new_project.py <工作目录> \
  --title "基于Spring Boot的XXX系统设计与实现" \
  --title-en "Design and Implementation of ..." \
  --name 张三 --student-id 20220001 \
  --college 数学与信息科技学院 --major 计算机科学与技术 --advisor 李四
```

生成 `manuscript.md`（章节骨架+图表位置+写作提示）、`outline.md`、`paper-context/`（事实源、缺证清单、图登记表）、`specs/`（9 张标准图 + `entity-attributes.json` 实体属性清单）、`figs/`、`output/`。

### 第 2 步：通读源码，建立证据

```bash
python <skill>/scripts/scan_project.py <源码目录> --out paper-context/project-evidence
```

然后**人工精读关键文件**（脚本只给线索）：

- 技术栈与版本：`pom.xml`/`package.json`/`requirements.txt`/配置文件。
- 角色与权限：登录、token、拦截器、角色判断、越权控制。
- 核心业务闭环：下单/支付/状态流转/取消回滚，能画出流程图。
- 数据库：表名、字段、类型、注释、索引、关联（到字段级）。
- 接口：路径、方法、入参/出参、统一返回、异常处理。
- 前端页面：用户端/管理端页面清单，对应第 5 章小节。
- 测试材料：用例/日志/报告/断言；没有就登记缺口。

产出 `paper-context/spec.md`（或直接维护 `project-evidence.md`）：题目、角色、功能模块、技术栈、流程、表、接口、测试、缺证清单。**这是后续写作的唯一事实源。**

### 第 3 步：按硬性大纲起草

读 `references/01-outline-spec.md` 与 `references/05-chapter-guide.md`。确认：

- 第 3 章：3.1.1 角色 / 3.1.2 功能需求（图3.1、图3.2）/ 3.1.3 非功能；3.2.1–3.2.3 可行性。
- 第 4 章：4.1 设计流程（图4.1–4.4）；4.2 总体结构（图4.5、图4.6）；4.3 数据库（4.3.1 描述+图4.7+**每个实体一张实体属性图（图4.8 起）**；4.3.2 表间关系+字段清单；4.3.3 三线表）。
- 第 5 章：按用户端/管理端模块，每节预留截图位置。
- 第 6 章：6.1 目的/6.2 方法/6.3 内容（用例表）/6.4 结论。
- 结论/参考文献/致谢/附录。

把大纲和图表落位写入 `outline.md`；模块名一旦确定，图4.6、第 5 章小节、测试用例三处必须一致。

### 第 4 步：逐章成文（不要一次性写完再改）

写作顺序：**第 3 章 → 第 4 章 → 第 5 章 → 第 6 章 → 第 1 章 → 第 2 章 → 结论**。

- 每章动笔前读 `references/02-writing-standards.md` 对应条款与 `references/05-chapter-guide.md` 该章施工图。
- 每段只讲一个判断；先给事实/证据，再给分析；图/表先引导后出现。
- 正文禁用过程措辞："根据源码/从代码看/待补充/占位/本地路径/源码文件名"。
- 写一章跑一次内容闸门（分章阶段加 `--draft`，否则总字数未达标会阻断）：

```bash
python <skill>/scripts/check_manuscript.py manuscript.md --draft --json output/content-check.json
```

ERROR 清零再写下一章；字数/匿名引用/超长句等 WARN 记录下来，第 6 步统一处理。**成稿前必须把正文（第1章–结论）总字数压进 12000–16000 字闭区间**，这是红线，多一个字少一个字都不行；成稿检查不带 `--draft`。字数不足时补有证据的业务细节/异常路径/测试断言，不要注水；超出时删重复综述与背景、合并同类小节，不要删设计论证和测试证据（详见 `05-chapter-guide.md` §0）。Word 的“全文统计”含封面/目录/摘要/参考文献等，通常比正文多 1500–3000 字；默认红线指正文，学校若按全文统计卡字数要先确认口径。

### 第 5 步：制作 Visio 图并插入

读 `references/04-figure-standards.md`。优先复用 `specs/` 里的标准规格，只改文字/模块名/实体名：

```bash
# 9 张标准结构图（用例/流程/架构/模块/E-R）
python <skill>/scripts/gen_figures.py --spec-dir specs --outdir figs

# 每个实体一张实体属性图（图4.8 起，数量必须等于 E-R 实体数）
python <skill>/scripts/gen_entity_attributes.py --spec specs/entity-attributes.json --outdir figs
```

产出 `figs/图X.Y题注.vsdx` 与 `.png`。生成后**逐张打开 PNG 检查**：文字不溢出、连线不穿字、标签不压框、无裁切；**除实体属性图外，所有连线必须横平竖直，不能有斜线**；实体属性图按“实体居中、属性椭圆环绕、直线辐射”的版式，允许斜直线；箭头必须由源指向目标，判断分支必须标“是/否”。`gen_figures.py --check` 会自动检查斜线段、箭头方向、起止节点、可达性和分支标签；`gen_entity_attributes.py --check` 检查实体属性图版式。把图按章节插入 `manuscript.md`：

```markdown
如图4.1所示，系统按照需求分析、总体设计、数据库设计、功能开发与系统测试五个阶段推进。

![图4.1　系统总体设计流程图](figs/图4.1系统总体设计流程图.png)
```

第 5 章每节先放截图占位：

```markdown
![图5.1　首页界面](PENDING:首页)
```

提交前替换为真实截图。更新 `paper-context/figure-registry.json` 状态。

### 第 6 步：降 AIGC（全文整体处理）

读 `references/03-humanize-standards.md`，严格执行：

- 场景决策（§0）→ 定全文"基础嗓音"（C1/C2）→ A 语义层（A1 脱稿重写/A2 段结构手术/A3 具名引用/A4 真实锚点）→ B 句层（B1–B5）→ C 文档层（C1–C6）。
- 高危段（引言/综述/讨论/结论）必须 A1 脱稿重写；禁止只做同义词/标点级修补（X1/X4）。
- 忠于事实、数据、术语、引文；缺素材写入 paper-context/gaps.md，不把【待作者补充】写进成品，**禁止为降 AI 率虚构数据/文献/经历**（X8）。
- 全文整体处理，不只改标红段（X5/C1）；"人味"是围绕个人基线的有限波动，不是每句都改怪（B3 边界）。
- 跑 S1–S12 自检，附 JSON 摘要；先降 AIGC 后跑查重；复测留 2–5 点裕量；不针对单一检测器过拟合（C6）。
- 禁止"保证通过/100% 人类"表述。

### 第 7 步：质检（三道闸门）

```bash
# 1) 图规格闸门：斜线/箭头方向/主流程/起止/可达性/分支标签
python <skill>/scripts/gen_figures.py --spec-dir specs --check
python <skill>/scripts/gen_entity_attributes.py --spec specs/entity-attributes.json --check

# 2) 内容闸门：结构/字数硬红线 12000–16000/实体属性图覆盖/图表编号/引用闭合/未完成措辞/降AIGC机械指标
python <skill>/scripts/check_manuscript.py manuscript.md --json output/content-check.json --out output/content-check.md

# 3) 生成 docx（提交版：PNG 内嵌）
python <skill>/scripts/build_docx.py manuscript.md --out output/论文_排版前.docx
python <skill>/scripts/paginate_tables.py output/论文_排版前.docx --out output/论文.docx

# 4) 更新目录/页码域并导出 PDF
python <skill>/scripts/update_fields.py output/论文.docx --pdf output/论文.pdf

# 5) docx 结构闸门（提交版）
python <skill>/scripts/check_docx.py output/论文.docx --manuscript manuscript.md

# 6) 可编辑版：把第3–4章结构图原位替换为 VSDX OLE（第5章截图仍用 PNG）
python <skill>/scripts/embed_vsdx.py output/论文.docx --figs figs \
    --out output/论文_可编辑版.docx --pdf output/论文_可编辑版.pdf

# 7) docx 结构闸门（可编辑版，自动核对 VSDX OLE / EMF 预览数量）
python <skill>/scripts/check_docx.py output/论文_可编辑版.docx --manuscript manuscript.md
```

任何 ERROR 必须修复并重跑；WARN 逐条判断。最后按 `references/07-quality-gates.md` 闸门 6 逐页核对 PDF 版面（目录页码、空白页、孤行、图注分离、整表同页或逐页同号续表、大图撑页）。

### 双版本交付规则（必守）

| 版本 | 文件 | 图的形式 | 用途 |
|---|---|---|---|
| 提交版 | `output/论文.docx` / `论文.pdf` | PNG 内嵌 | 提交、盲审、打印；兼容 WPS/在线预览/各类转换器 |
| 可编辑版 | `output/论文_可编辑版.docx` / `.pdf` | 第3–4章结构图为 VSDX OLE，第5章截图为 PNG | 导师审阅、答辩前改图；双击图可进 Visio 编辑，PDF 导出为矢量 |

- 两版必须由**同一次** `build_docx.py` 产物派生，保证章节、图号、图位置、题注完全一致。
- PNG 不是“废文件”：它是提交版的显示图、作图后的检视图、以及 OLE 不可用环境的兜底；`figs/` 必须同时保留 `.vsdx` + `.png`。
- 可编辑版的 OLE 是 docx 内嵌副本：在 Word 里双击修改**不会**同步外部 `.vsdx`；要长期维护，改 `specs/*.json` 重新生成 vsdx，再重跑 `embed_vsdx.py`。
- 可编辑版导出 PDF 必须用 Word（`update_fields.py` 已调用 Word 导出）；不要用 WPS/在线转换，避免 OLE 预览丢失。
- 第 5 章界面截图没有 vsdx，永远用 PNG；`embed_vsdx.py` 默认只替换第 3–4 章结构图。

### 第 8 步：交付

输出交付报告（五部分）：

1. **产物**：`output/论文.docx`、`output/论文.pdf`（提交版）、`output/论文_可编辑版.docx`、`output/论文_可编辑版.pdf`、`figs/*.vsdx`、`figs/*.png`；章节数、图表数、总字数、VSDX OLE 数量。
2. **闸门结果**：内容闸门 ERROR/WARN 数、docx 闸门结果、PDF 抽页结论（贴命令与关键输出）。
3. **仍需人工确认**：缺证清单、待替换截图、参考文献待核对项、学校模板差异。
4. **披露提醒**：若场景要求披露 AI 辅助，附 `03-humanize-standards.md` §7 模板。
5. **免责**：不构成任何检测器通过保证；检测是概率性、版本相关的；最终验收是作者可辩护。

## 工作区结构

```
<工作目录>/
├── manuscript.md                  唯一文字源（front matter + 章节 + 图表）
├── outline.md                     硬性大纲、图表落位、字数计划
├── paper-context/
│   ├── project-evidence.json/.md  源码扫描线索
│   ├── spec.md                    事实源（角色/模块/表/接口/测试）
│   ├── figure-registry.json       图登记表
│   └── gaps.md                    缺证清单
├── specs/*.json                   9 张标准图规格 + entity-attributes.json
├── figs/*.vsdx / *.png            可编辑源 + 插图（含每个实体的属性图）
└── output/
    ├── 论文.docx / 论文.pdf             提交版（PNG 内嵌）
    ├── 论文_可编辑版.docx / .pdf        可编辑版（第3–4章 VSDX OLE）
    └── content-check.json/.md
```

## 命令速查

| 目的 | 命令 |
|---|---|
| 新建工作区 | `python <skill>/scripts/new_project.py <dir> --title "..." --name ...` |
| 扫描源码 | `python <skill>/scripts/scan_project.py <src> --out paper-context/project-evidence` |
| 校验图规格（含斜线/箭头/逻辑） | `python <skill>/scripts/gen_figures.py --spec-dir specs --check` |
| 批量生成结构图 | `python <skill>/scripts/gen_figures.py --spec-dir specs --outdir figs` |
| 校验实体属性图配置 | `python <skill>/scripts/gen_entity_attributes.py --spec specs/entity-attributes.json --check` |
| 批量生成实体属性图 | `python <skill>/scripts/gen_entity_attributes.py --spec specs/entity-attributes.json --outdir figs` |
| 内容闸门（分章草稿） | `python <skill>/scripts/check_manuscript.py manuscript.md --draft` |
| 内容闸门（成稿，字数硬红线） | `python <skill>/scripts/check_manuscript.py manuscript.md` |
| 生成 docx（分页前） | python <skill>/scripts/build_docx.py manuscript.md --out output/论文_排版前.docx |
| 整表同页/生成续表 | python <skill>/scripts/paginate_tables.py output/论文_排版前.docx --out output/论文.docx |
| 更新域/导 PDF | `python <skill>/scripts/update_fields.py output/论文.docx --pdf output/论文.pdf` |
| 生成可编辑版（VSDX OLE） | `python <skill>/scripts/embed_vsdx.py output/论文.docx --figs figs --out output/论文_可编辑版.docx --pdf output/论文_可编辑版.pdf` |
| docx 闸门 | `python <skill>/scripts/check_docx.py output/论文.docx --manuscript manuscript.md` |
| 打印机环境自检 | `python <skill>/scripts/office_prepare.py --status` |

> Windows + Microsoft Office 环境下，Visio 与 Word 自动化已内置；没有 Office 时，`gen_figures.py`、`embed_vsdx.py` 与 `update_fields.py` 无法运行，需改用人工导出/更新，并在交付报告中注明。

### 关于默认打印机（重要）

Word 与 Visio 在启动和刷新分页（`Repaginate`）时**必须**读取默认打印机来获取纸张尺寸与可打印区域，这是它们的版面度量机制，无法通过参数关闭。如果默认打印机是网络打印机（WSD / IPP / TCP 端口），每次自动化都会去探测那台设备：设备离线时 Word 可能卡住数十秒到数分钟，在线时也可能让打印机面板亮起，看起来像"自动去连了打印机"。

本技能的 `update_fields.py`、`embed_vsdx.py`、`gen_figures.py` 已统一接入 `scripts/office_prepare.py`：在启动 Office 前把默认打印机**临时**切到本地虚拟打印机（优先 `Microsoft Print to PDF`），结束后（含异常路径）自动恢复用户原来的设置。它只改变默认打印机这一项，不做任何真实打印，也不影响用户随时手动打印。

- 查看当前状态：`python <skill>/scripts/office_prepare.py --status`
- 若自动化日志出现 `[office_env] 未找到可用的本地虚拟打印机`，说明机器上只有网络打印机；此时 Word 每次仍会去探测设备，可考虑安装"Microsoft Print to PDF"功能或把一台本地队列设为默认。
- **不需要也不应该**为此安装 LibreOffice：本技能全部转换工作由本机 Microsoft Word / Visio 的 COM 接口完成。

## 参考文件索引

| 文件 | 内容 | 何时读 |
|---|---|---|
| `references/01-outline-spec.md` | 硬性大纲规范（六章结构、第 4 章数据库三小节做法） | 第 3 步起草大纲 |
| `references/02-writing-standards.md` | 通用写作规范全文（分节/字体/前置部分/图表/技术呈现/语言/Word+PDF 检查/返工表） | 每章写作前；第 7 步对照 |
| `references/03-humanize-standards.md` | 降 AIGC 规范全文（场景/原理/五原则/A·B·C 规则/禁止项/S1–S12/披露模板） | 第 6 步；交付前 |
| `references/04-figure-standards.md` | 标准结构图 + 每个实体属性图的画法、正交连线/箭头规则、生成与插入 | 第 5 步 |
| `references/05-chapter-guide.md` | 逐章施工图：每节写什么、多少字、证据从哪来、自检 | 第 4 步 |
| `references/06-docx-production.md` | 稿件 Markdown 约定、6 分节/页码/TOC/三线表/占位符落法 | 第 7 步 |
| `references/07-quality-gates.md` | 闸门 0–6、验收标准、交付报告模板、红线 | 第 7–8 步 |
| references/08-template-and-pagination.md | 前置页来源、字段绑定、同页/续表策略、Word 实际分页验收 | 生成/维护 DOCX 前必读 |
| references/09-hbks-format-profile.md | 8 篇同校论文实证的真实格式档案（页面/封面/声明/摘要/标题/图表/参考文献逐项取值与一致度） | 核对本校真实格式、维护技能、写格式规范时 |
| `assets/标准示例图/` | 10 张 Visio 风格基准图 | 第 5 步对照 |
| `assets/figure-specs/` | 9 张标准图规格 + `entity-attributes.json` | 第 5 步复用/改字 |

## 维护后的验证

运行 scripts/test_layout_regression.py --out <独立测试目录> --word，验证模板绑定、缺信息阻断、短表移页、多页续表、拆表数据不丢重、重复运行不再拆表、旧分页报告失效。实际 Word 导出 PDF 后目检封面/声明及全部表段，不能用 XML 检查代替版面验收。

## 红线速记

1. **正文总字数（第1章–结论）必须在 12000–16000 字闭区间**；多一个字少一个字都不行，成稿检查不带 `--draft`。
2. **实体属性图必须覆盖 E-R 图中的每一个实体**，不是只画一张；图4.8 起按实体顺序连续编号。
3. **图表连线**：除实体属性图外，所有连线只能横平竖直（允许 90° 折线，禁止斜线/斜箭头）；实体属性图用中心辐射直线版式（允许斜直线，不加箭头）；箭头必须由源指向目标，判断分支必须标“是/否”，开始/结束与可达性必须正确。
4. 学校/导师规则 > 本技能默认值。
5. 不编造功能、字段、接口、测试结果、截图、文献、数据、学校规定；缺失就列缺口。
6. 第 5 章不放测试，第 6 章不放功能截图；无独立结论要求则不设第 7 章。
7. 正文禁止过程措辞与证据语言；图/表先引导后出现，图题注在下、表题注在上。
8. 降 AIGC 不虚构、不隐瞒、不保证过检、不针对单检测器过拟合。
9. docx 变更后必须重跑闸门；相邻 .layout.json 必须匹配最终 DOCX 哈希，闸门不过不得声称完成。
10. **三线表必须整表同页；本身超页时逐页同号续表、完整表头、独立三线边框，不能只有重复表头。**
11. 前置页按核验模板绑定，禁止残留机器槽位、挪用他人签名、硬填未知日期。
