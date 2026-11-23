# docx 生产与排版落地

> 目标：从 `manuscript.md` 一键生成“结构正确、域可更新、三线表规范、图注不分离”的 `.docx`，再导出 PDF 做版面核对。
> 学校官方模板优先于本文件的默认值。

## 1. 稿件格式约定

`build_docx.py` 只认这一套 Markdown 约定，写稿时必须遵守。

### 1.1 front matter

```markdown
---
school: 河北科技师范学院
doc_type: 学士学位论文
title: 基于Spring Boot的手机租赁系统设计与实现
title_en: Design and Implementation of ...
name: 张三
student_id: 20220001
college: 数学与信息科技学院
major: 计算机科学与技术
advisor: 李四
date: 二〇二六年五月
header: 河北科技师范学院学士学位论文
---
```

- header、front_template 可选；header 缺省为“{school}学士学位论文”；front_template 缺省为内置模板，自定义时只填实际路径，不加行内注释。
- title/name/student_id/college/major/advisor/date 必填，缺失/含占位词时报错。signature_date 只有确认后填写，不能从 date 推断。默认封面不显示 title_en。见 08-template-and-pagination.md。

### 1.2 标题

- `#` 一级：摘要、ABSTRACT、目录、第X章、结论、参考文献、致谢、附录。
- `##` 二级：X.X。
- `###` 三级：X.X.X。
- 全角空格分隔编号与标题，如 `# 第1章　绪论`、`## 3.1　系统总体需求分析`。
- 标题必须用 Markdown 标题语法（脚本会套 Word 内置 Heading 1/2/3 样式），禁止手工加粗冒充。

### 1.3 表格

表题注在表格**上方**，单独一行，以“表X.Y”开头；紧接着是 Markdown 表格：

```markdown
表4.1　用户表(user)
| 编号 | 字段名 | 类型 | 长度 | 是否非空 | 是否主键 | 注释 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | id | bigint | - | 是 | 是 | 主键ID |
```

- 脚本自动生成三线表（顶线/栏目线/底线，无竖线），题注与整表同页；Word 实测超页才拆同号续表，行内不得断页。
- 手工拆表时（最终仍须 Word 验收）：在续页表前写 `续表4.1　用户表(user)` + 表头 + 剩余行；脚本识别续表题注并在新页排表。
- 字段表“注释”列 ≤4 个汉字；长说明移到正文或表下注。

### 1.4 图片

图题注在图片**下方**，写在 `alt` 里：

```markdown
![图4.1　系统总体设计流程图](figs/图4.1系统总体设计流程图.png)
```

- 相对路径按 manuscript.md 所在目录解析。
- 可指定宽度：`![图4.1　...](figs/...png){width=12cm}`；缺省 15 cm。
- 第五章截图占位：`![图5.1　首页界面](PENDING:首页)`；脚本渲染虚线占位框 + 正常题注。
- `build_docx.py` 会把题注同时写入图片的替代文字（`descr`），`embed_vsdx.py` 靠它按“图X.Y”精确匹配 vsdx；不要手工删除这个属性。

### 1.5 其他

- `<!--TOC-->`：自动目录域位置（通常放在“目　　录”标题下）。
- `<!--PAGEBREAK-->`：强制分页。
- `<!-- 注释 -->`：写作提示/内部注释，**不进入正文**；支持多行注释。
- 正文段落一行一段；`**加粗**` 行内生效；`[1]` 自动转上标引用。
- `- 列表项` 渲染为项目符号段落（论文正文尽量少用列表）。
- 参考文献区：每条以 `[n]` 开头，脚本做悬挂缩进。

## 2. 生成 docx

```bash
python <skill>/scripts/build_docx.py manuscript.md --out output/论文_排版前.docx
python <skill>/scripts/paginate_tables.py output/论文_排版前.docx --out output/论文.docx
```

生成 6 节：

| 节 | 内容 | 页码 | 页眉 |
|---|---|---|---|
| 1 | 封面 | 无 | 无 |
| 2 | 原创性声明 + 版权授权书（同在一页） | 无 | 无 |
| 3 | 中文摘要 | 罗马 i 起 | 无 |
| 4 | ABSTRACT | 罗马续 | 无 |
| 5 | 目录（TOC 域） | 罗马续 | 无 |
| 6 | 正文—附录 | 阿拉伯 1 起 | ××学院学士学位论文 |

格式基线：

- A4；上 2.5 / 下 2.0 / 左 2.0 / 右 2.0 cm；装订线 0.5 cm；页眉 1.5 / 页脚 1.75 cm。
- 章标题黑体三号（15 pt）加粗居中；节标题黑体四号（14 pt）左对齐不加粗；小节黑体 13 pt 加粗。
- 正文宋体/Times New Roman 小四（12 pt），两端对齐，首行缩进 2 字符，固定行距 20 pt。
- 图/表题注 10.5 pt 居中；页眉页脚 9 pt。
- 自动目录显示 1–3 级；摘要/ABSTRACT/目录标题不进入目录。

> 若学校模板的字体/页边距不同，先按 08-template-and-pagination.md 建项目专用模板副本，核验节映射后再改 `build_docx.py` 顶部常量或直接替换封面/声明页；不要改章节结构。

## 3. 更新域并导出 PDF

```bash
python <skill>/scripts/update_fields.py output/论文.docx --pdf output/论文.pdf
```

脚本会：

1. 更新正文所有域；
2. 逐节更新页眉/页脚 PAGE 域；
3. 更新自动目录（TOC）；
4. 保存 docx；
5. 导出 PDF（可选指定页范围 `--pages 1-12`）。

**必须在 Microsoft Word 实际重排后确认**：目录条目页码与正文实际页码一致；页脚不是缓存旧值；封面/声明无页码。

### 2.1 关于默认打印机

`update_fields.py` 调用 Word 更新域时会启动 Word，而 Word 启动与刷新分页**必须**读取默认打印机来获取纸张尺寸与可打印区域。若默认打印机是网络打印机（WSD/IPP/TCP 端口），Word 会去探测设备：离线时会卡住很久，在线时会触发设备面板反应。

脚本已通过 `scripts/office_prepare.py` 处理：启动 Word 前把默认打印机临时切成本地虚拟打印机（优先 `Microsoft Print to PDF`），结束后自动恢复。无需手工干预，也不产生任何真实打印。自检命令：

```bash
python <skill>/scripts/office_prepare.py --status
```

**本流程不需要 LibreOffice。** 域更新、PDF 导出、VSDX OLE 嵌入全部由本机 Microsoft Word / Visio 的 COM 接口完成；LibreOffice 渲染的中文字体与版面反而可能与 Word 有偏差。

## 3.1 可编辑版（VSDX OLE，双版本交付）

提交版 docx 用 PNG 内嵌，兼容性最好；可编辑版把第 3–4 章结构图原位替换成 VSDX OLE 对象，双击可进 Visio 编辑，导出 PDF 为矢量。

```bash
python <skill>/scripts/embed_vsdx.py output/论文.docx --figs figs \
    --out output/论文_可编辑版.docx --pdf output/论文_可编辑版.pdf
```

实现要点（脚本已处理，手工改时也要注意）：

1. `python-docx` 不能插 OLE，必须用 Word COM。
2. **不能** `AddOLEObject(Range=图片.Range)`：长文档里会把对象插到文档开头。正确做法是 `doc.Range(pos, pos).InlineShapes.AddOLEObject(...)` 在零长度位置插入。
3. 顺序必须是“先插入新 OLE、再删除旧图片”，并从文档最后一个图往前处理，位置才稳定。
4. 插入后 `LockAspectRatio=False`，把 `Width/Height` 设回原图尺寸，版面不跳。
5. 图片的替代文字（`descr`）已由 `build_docx.py` 写成图题注（如“图4.1　系统总体设计流程图”），脚本按“图X.Y”精确匹配 vsdx，避免图4.1误配图4.10。
6. 第 5 章截图没有 vsdx，保留 PNG；封面校徽等无图号的图片不替换。
7. 每个 OLE 对象都会带一份 EMF 预览（`word/media/*.emf`）；没有 Visio 的机器通常也能显示，只是不能编辑。

两版的分工：

| 版本 | 图 | 用途 | 注意 |
|---|---|---|---|
| `论文.docx/.pdf` | PNG 内嵌 | 提交、盲审、打印 | 兼容 WPS/在线预览/各类转换器 |
| `论文_可编辑版.docx/.pdf` | 第3–4章 VSDX OLE，第5章 PNG | 导师审阅、答辩前改图 | 用 Word 导出 PDF，别用 WPS/在线转换 |

> OLE 是 docx 内嵌副本，在 Word 里双击修改不会同步外部 `.vsdx`。要长期维护，改 `specs/*.json` → 重新生成 vsdx → 重跑 `embed_vsdx.py`。
> `figs/` 必须同时保留 `.vsdx` 与 `.png`：PNG 是提交版显示图、作图检视图、OLE 不可用环境的兜底。

## 4. 结构闸门

```bash
python <skill>/scripts/check_docx.py output/论文.docx --manuscript manuscript.md
```

检查项与处理（默认同时要求当前 DOCX 匹配的 .layout.json；缺失或过期均阻断）：

| 检查 | 不通过时 |
|---|---|
| 分节数 <6 | 检查标题是否用了 `#` 一级，摘要/ABSTRACT/目录/第1章是否齐全 |
| 页码格式错 | 检查 `set_pgnum` 逻辑或手动在 Word 设置页码格式 |
| 正文页眉缺失 | front matter `header` 或第 1 章标题是否被识别 |
| 无 TOC 域 | 检查 `<!--TOC-->` 是否在“目录”标题下 |
| 表格非三线表 | 检查表格是否走 Markdown 表格语法，是否被误当正文 |
| 图片宽度 >15.5 cm | 用 `{width=...}` 或压缩原图 |
| 有“待补充/TBD” | 回到稿件清除 |
| 实体属性图数量不足 | 先跑 `check_manuscript.py`，改 `entity-attributes.json` 后重新生成 |
| 可编辑版 VSDX OLE 数量与结构图数不一致 | 重跑 `embed_vsdx.py`，看“保留 PNG 明细”里是否缺 vsdx |

> 生成 docx 之前必须先过内容闸门：正文总字数（第1章–结论）必须落在 12000–16000 字，且 E-R 图每个实体都有实体属性图；否则不要进入排版。
> 可编辑版再跑一次 `check_docx.py`：它会自动识别 `word/embeddings/*.vsdx`，核对 OLE 数量与 EMF 预览数量。

## 5. 版面核对（PDF 逐页）

按 `02-writing-standards.md` §10 执行，重点：

- 目录页码与实际一致（抽查 ≥3 处）；目录显示到三级。
- 封面/声明无页眉页码；摘要区罗马、正文区阿拉伯且为最新值。
- 无异常空白页（尤其分节处）。
- 无孤行：页底不只剩一行正文；图题注不孤悬页底。
- 图与“如图X.Y所示”尽量同页；大图不撑页、不留大面积空白。
- 短表整表同页；超长表每个续页有同号续表题注、完整表头、三线边框，且表段各自同页。
- 截图清晰、无拉伸、无未完成界面。
- 字体无乱码/方框；页边距四周均匀。

## 6. 第五章截图替换

1. 打开 `manuscript.md`，找到 `![图5.x　题注](PENDING:界面名)`。
2. 把 `PENDING:界面名` 换成真实图片相对路径，例如 `figs/首页.png`。
3. 重跑 `build_docx.py` → `update_fields.py` → `check_docx.py`。
4. 确认占位数量为 0、图片数量与稿件一致、图注仍在下。

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 目录是灰字“请在 Word 中更新” | 未更新域 | 运行 `update_fields.py`，或 Word 中全选 F9 |
| 每节页码都从 i/1 开始 | 节复制了 `w:start` | 脚本已处理；若手改 Word，检查“页码→设置页码格式→续前节” |
| 目录包含摘要/ABSTRACT/目录 | 它们用了 Heading 1 | 脚本用 `Front Heading` 样式排除；手改时把大纲级别设为“正文文本” |
| 图注跑到下一页、图在上一页 | 图片段未与下段同页 | 脚本已设置 `keep_with_next`；仍分离则图前分页或缩图 |
| 表跨页无续表 | 仅重复表头，未做显式拆表 | 运行 paginate_tables.py → update_fields.py → check_docx.py |
| 表格有竖线/内部横线 | 用了 Word 默认表格样式 | 删表重插，确保走 Markdown 表格；或手动设三线 |
| 封面出现页眉页码 | 封面与正文未分节 | 检查是否 6 节；封面节页眉页脚应为空 |
| 文档属性作者是 Administrator | 未设置 | front matter `name` 会写入；手改在“文件→信息→属性” |
