#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_project.py —— 新建一个论文工作区（骨架 + 标准图规格 + 图登记表）

用法：
  python new_project.py D:/paper/我的毕设 \
      --title "基于Spring Boot的手机租赁系统设计与实现" \
      --name 张三 --student-id 20220001 --college 数学与信息科技学院 \
      --major 计算机科学与技术 --advisor 李四

生成：
  manuscript.md                 论文稿（章节骨架 + 图表位置 + 写作提示）
  outline.md                    硬性大纲与图表/字数计划
  paper-context/figure-registry.json
  paper-context/spec.md         事实源模板（角色/模块/表/接口/测试）
  paper-context/gaps.md         缺证清单模板
  specs/*.json                  9 张标准图规格 + entity-attributes.json（每个实体一条）
  figs/                         放生成的 .vsdx/.png
  output/                       放最终 docx/pdf（提交版 + 可编辑版）
  README.md                     工作流命令
"""
import argparse
import json
import os
import shutil
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(SKILL_ROOT, "assets", "figure-specs")

BASE_FIGURES = [
    ("图3.1", "普通用户用例图", "3.1.2", "fig3-1-user-usecase.json"),
    ("图3.2", "管理员用例图", "3.1.2", "fig3-2-admin-usecase.json"),
    ("图4.1", "系统总体设计流程图", "4.1.1", "fig4-1-overall-flow.json"),
    ("图4.2", "用户注册登录流程图", "4.1.2", "fig4-2-login-flow.json"),
    ("图4.3", "下单流程图", "4.1.3", "fig4-3-order-flow.json"),
    ("图4.4", "订单业务流程图", "4.1.4", "fig4-4-order-business-flow.json"),
    ("图4.5", "系统总体架构图", "4.2.1", "fig4-5-architecture.json"),
    ("图4.6", "系统功能模块结构图", "4.2.2", "fig4-6-module-tree.json"),
    ("图4.7", "系统总体E-R图", "4.3.1", "fig4-7-er.json"),
]
ENTITY_SPEC = "entity-attributes.json"


def load_entities():
    path = os.path.join(SPEC_DIR, ENTITY_SPEC)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("entities", [])


def entity_figures(entities):
    start = 8
    return [(f"图4.{start + i}", f"{e['name']}实体属性图", "4.3.1", ENTITY_SPEC)
            for i, e in enumerate(entities)]


def entity_attr_block(entities):
    """生成 4.3.1 的实体属性图段落（每个实体一张图，先引导后出现）。"""
    if not entities:
        return ""
    lines = []
    if len(entities) == 1:
        lines.append("该实体的主要属性如图4.8所示。")
    else:
        lines.append(f"各实体的主要属性如图4.8至图4.{7 + len(entities)}所示。")
    lines.append("")
    for i, e in enumerate(entities):
        n = 8 + i
        name = e["name"]
        lines.append(f"如图4.{n}所示，{name}实体记录其在业务中的关键属性。")
        lines.append("")
        lines.append(f"![图4.{n}　{name}实体属性图](figs/图4.{n}{name}实体属性图.png){{width=12cm}}")
        lines.append("")
    return "\n".join(lines).rstrip()

MANUSCRIPT = """---
school: {school}
doc_type: 学士学位论文
title: {title}
title_en: {title_en}
name: {name}
student_id: {student_id}
college: {college}
major: {major}
advisor: {advisor}
date: {date}
header: {school}学士学位论文
---

# 摘　　要

<!-- 写作提示：一段式，①背景1–2句 ②问题1句 ③方法/技术路线1–2句 ④主要结果2–3句 ⑤意义1句；约350–500字。
     禁止写成“第1章介绍了……第2章分析了……”的目录复述。结果必须与第5、6章一致。 -->
<!-- 关键词：3–8个，分号分隔，必须能从正文中命中 -->

# ABSTRACT

<!-- 写作提示：与中文摘要内容、详略基本一致，正式书面英语；不得明显缩水。 -->
<!-- Key words: 与中文关键词一一对应，逗号分隔 -->

# 目　　录

<!--TOC-->

# 第1章　绪论

## 1.1　研究背景

<!-- 写作提示：3段左右。行业/社会背景 → 现有做法的问题 → 本课题的必要性。不要从“随着信息技术的飞速发展”起笔。 -->

## 1.2　国内外研究现状

### 1.2.1　国外研究与发展现状

<!-- 写作提示：按主题/维度综述，不要按时间流水账；每个观点要有具名文献支撑 [1]。 -->

### 1.2.2　国内研究与应用发展现状

<!-- 写作提示：同上；最后一段归纳差距（现有系统重后台轻前端、重展示轻流程等），自然引出本文。 -->

## 1.3　本文研究内容与技术路线

<!-- 写作提示：写清研究内容（功能+技术+测试）与技术路线（需求→设计→实现→测试）；不要写成目录复述。 -->

# 第2章　相关技术介绍

<!-- 写作提示：只写项目真实使用的技术。每节统一“技术简介→选型理由→本项目落点”，不要写成 API 手册。
     按实际技术栈增删小节，建议 4–7 节。 -->

## 2.1　{tech1}

## 2.2　{tech2}

## 2.3　{tech3}

## 2.4　{tech4}

# 第3章　系统需求分析

## 3.1　系统总体需求分析

### 3.1.1　用户角色分析

<!-- 写作提示：列出普通用户/管理员等角色，各自能做什么、不能做什么；可配角色表。 -->

### 3.1.2　功能需求分析

<!-- 写作提示：按业务模块写功能需求，每条需求可验证；此处插入普通用户与管理员用例图。 -->

如图3.1所示，普通用户围绕设备浏览、租赁下单、支付与订单管理等环节使用系统。

![图3.1　普通用户用例图](figs/图3.1普通用户用例图.png)

如图3.2所示，管理员主要负责用户、设备、订单、社区内容与系统配置等管理工作。

![图3.2　管理员用例图](figs/图3.2管理员用例图.png)

### 3.1.3　非功能需求分析

<!-- 写作提示：性能、安全、易用性、可维护性、兼容性；给出可度量的指标或合理约束，不空喊口号。 -->

## 3.2　可行性分析

### 3.2.1　技术可行性

### 3.2.2　经济可行性

### 3.2.3　操作可行性

# 第4章　系统设计

## 4.1　系统设计流程

### 4.1.1　系统总体设计流程

<!-- 写作提示：需求分析→总体设计→数据库设计→功能开发→系统测试；配图并在图后分析。 -->

如图4.1所示，系统按照需求分析、总体设计、数据库设计、功能开发与系统测试五个阶段推进。

![图4.1　系统总体设计流程图](figs/图4.1系统总体设计流程图.png)

### 4.1.2　用户注册登录流程

<!-- 写作提示：写清注册/登录判定、JWT 生成与保存、失败重试；配图后逐段解释分支。 -->

如图4.2所示，用户进入登录页面后先判断是否已有账号，再完成注册或登录校验。

![图4.2　用户注册登录流程图](figs/图4.2用户注册登录流程图.png)

### 4.1.3　用户下单流程

<!-- 写作提示：浏览→详情→选择租期/地址/优惠券→提交→库存与有效性校验→算价→扣库存建单→写快照。 -->

如图4.3所示，下单流程在提交订单后依次校验设备可租性与地址、优惠券有效性。

![图4.3　下单流程图](figs/图4.3下单流程图.png)

### 4.1.4　订单支付与状态流转流程

<!-- 写作提示：待支付→待发货→使用中→待归还→已完成；取消/超时关闭时库存与优惠券如何回滚。 -->

如图4.4所示，订单从创建待支付订单开始，经过支付、发货、收货、归还直至结束。

![图4.4　订单业务流程图](figs/图4.4订单业务流程图.png)

### 4.1.5　系统操作流程

<!-- 写作提示：从用户打开系统到完成一次核心业务的端到端操作路径；避免重复 4.1.1–4.1.4。 -->

## 4.2　系统总体结构设计

### 4.2.1　系统架构设计

<!-- 写作提示：前端/后端/数据库/第三方分层与职责边界；说明访问入口、鉴权与数据流。 -->

如图4.5所示，系统由微信小程序端、后台管理端、后端服务端与数据存储层组成。

![图4.5　系统总体架构图](figs/图4.5系统总体架构图.png)

### 4.2.2　用户端功能结构设计

<!-- 写作提示：模块树按实际功能改；配图后说明各模块职责，不要只列名词。 -->

如图4.6所示，系统按用户端、管理端与后端服务端划分为三类功能模块。

![图4.6　系统功能模块结构图](figs/图4.6系统功能模块结构图.png)

### 4.2.3　管理端功能结构设计

### 4.2.4　后端业务模块结构设计

## 4.3　数据库设计

### 4.3.1　概念结构设计

<!-- 写作提示：先用一段话概括核心实体与联系，再给总体 E-R 图；E-R 图中的每个实体都必须单独画一张实体-属性图。 -->

系统核心实体包括用户、设备、订单、支付记录与社区内容等，实体之间通过业务关系相互关联。系统总体 E-R 图如图4.7所示。

![图4.7　系统总体E-R图](figs/图4.7系统总体E-R图.png)

{entity_attr_block}

### 4.3.2　逻辑结构设计

<!-- 写作提示：先写表间关联（谁通过哪个外键关联谁），再逐个实体列出字段清单；多态关系写清 target_type/target_id。 -->

### 4.3.3　物理结构设计

<!-- 写作提示：每张核心表一个三线表：编号|字段名|类型|长度|是否非空|是否主键|注释；注释≤4个汉字。
     表前用“表X.Y　表名”作题注，正文先有“如表X.Y所示”。 -->

# 第5章　系统实现

## 5.1　用户功能实现

### 5.1.1　首页内容展示

<!-- 写作提示：功能说明 + 交互路径/关键逻辑 + 界面截图（图注在下）；截图占位提交前替换。 -->

如图5.1所示，首页集中展示轮播图、推荐设备与快捷入口。

![图5.1　首页界面](PENDING:首页)

### 5.1.2　设备列表与详情

如图5.2所示，设备列表页支持按分类与关键词筛选并进入详情。

![图5.2　设备列表界面](PENDING:设备列表)

### 5.1.3　用户登录与个人中心

如图5.3所示，个人中心汇总用户资料、订单入口与账户信息。

![图5.3　个人中心界面](PENDING:个人中心)

### 5.1.4　租赁下单与支付

如图5.4所示，用户确认租期与地址后进入支付页面完成付款。

![图5.4　下单支付界面](PENDING:下单支付)

### 5.1.5　订单查看与归还

如图5.5所示，用户可在订单列表中查看状态并发起归还。

![图5.5　订单管理界面](PENDING:订单管理)

### 5.1.6　社区互动

如图5.6所示，社区页面支持发帖、评论与收藏。

![图5.6　社区互动界面](PENDING:社区互动)

## 5.2　管理员功能实现

### 5.2.1　管理员登录

如图5.7所示，管理员通过独立入口登录后台。

![图5.7　管理员登录界面](PENDING:管理员登录)

### 5.2.2　首页数据统计

如图5.8所示，后台首页以图表展示用户、订单与设备数据。

![图5.8　数据统计界面](PENDING:数据统计)

### 5.2.3　用户与设备管理

如图5.9所示，管理员可新增、编辑与上下架设备。

![图5.9　设备管理界面](PENDING:设备管理)

### 5.2.4　订单管理

如图5.10所示，管理员可查看订单并执行发货等操作。

![图5.10　后台订单管理界面](PENDING:后台订单管理)

### 5.2.5　社区内容管理

如图5.11所示，管理员可审核与删除社区内容。

![图5.11　社区内容管理界面](PENDING:社区内容管理)

### 5.2.6　系统配置

如图5.12所示，管理员可维护轮播图、优惠券与基础参数。

![图5.12　系统配置界面](PENDING:系统配置)

# 第6章　系统测试

## 6.1　测试目的

## 6.2　测试方法

<!-- 写作提示：黑盒功能测试为主，辅以接口测试/边界值/异常场景；写清环境与工具及版本号。 -->

## 6.3　测试内容

<!-- 写作提示：每类测试一张四列用例表：编号|测试模块|测试操作|预期结果。预期结果必须可验证。 -->

### 6.3.1　用户端功能测试

### 6.3.2　管理端功能测试

### 6.3.3　核心业务流程测试

### 6.3.4　接口与权限测试

## 6.4　测试结论

<!-- 写作提示：逐条对应第5章功能与第6章用例，不写“功能正常”这类空话；如实写局限。 -->

# 结　　论

<!-- 写作提示：两段左右概括完成的工作与效果，再写局限与后续方向；不要空喊“还有很多不足”。 -->

# 参考文献

<!-- 写作提示：GB/T 7714 顺序编码制；正文 [n] 与条目一一对应，不编造文献。 -->

# 致　　谢

<!-- 写作提示：半页到一页，真诚得体，不写班级昵称和网络流行语。 -->

# 附　　录

<!-- 写作提示：只放真实内容（核心代码/数据字典/问卷）；没有内容就删掉本节。 -->
"""

OUTLINE_TEMPLATE = """# 论文大纲与图表计划（硬性大纲版）

> 学校/导师模板优先。以下为默认六章结构；第2章与第5章按项目实际技术/模块增删小节。

| 章 | 必备内容 | 图 | 建议字数 |
|---|---|---|---|
| 第1章 绪论 | 1.1 背景；1.2 国内外现状（1.2.1 国外 / 1.2.2 国内）；1.3 研究内容与技术路线 | — | 1200–1800 |
| 第2章 相关技术介绍 | 每项技术：是什么→为何选→项目落点 | — | 1000–1500 |
| 第3章 系统需求分析 | 3.1 总体需求（角色/功能/非功能）；3.2 可行性（技术/经济/操作） | 图3.1 用户用例图；图3.2 管理员用例图 | 2000–2500 |
| 第4章 系统设计 | 4.1 设计流程；4.2 总体结构；4.3 数据库（概念/逻辑/物理） | 图4.1–4.4 流程；图4.5 架构；图4.6 模块；图4.7 E-R；图4.8 起为每个实体的实体-属性图 | 2800–3500 |
| 第5章 系统实现 | 按用户端/管理端模块：说明+交互+截图 | 每节至少 1 张界面截图（先用占位） | 3000–3900 |
| 第6章 系统测试 | 目的/方法/环境/用例表/结果/结论 | 测试环境表、用例表（无图） | 1400–1900 |
| 结论 | 完成工作+局限+展望 | — | 600–900 |
| 参考文献 | ≥10–15 条，GB/T 7714 | — | — |
| 致谢/附录 | 致谢半页到一页；附录必须有实际内容 | — | — |

> **全文红线**：正文（第1章–结论）总字数必须落在 **12000–16000 字** 闭区间，多一个字少一个字都不行；成稿检查使用 `check_manuscript.py`（不加 `--draft`）。

## 图表落位

| 图号 | 题注 | 所在小节 | 规格文件 |
|---|---|---|---|
{figure_rows}

## 写作纪律

1. 先证据后写作：每个功能/字段/接口/测试结论都能指回源码或运行结果。
2. 先骨架后填肉：标题只用 Heading 1/2/3，编号唯一，不跳级。
3. 图表先引导后出现：正文先写“如图X.Y所示”，图题注在图下、表题注在表上。
4. 第5章只写实现，不放测试；第6章只写测试，不放功能截图。
5. 降 AIGC 在成文过程中随章执行，不虚构数据/文献/经历。
"""

SPEC_TEMPLATE = """# 论文事实源（spec）

> 这是阶段二写作的唯一事实来源。每一条都必须能指回源码/数据库/接口/运行结果；没有证据的写“缺证”。

## 题目

- 中文：{title}
- 英文：{title_en}

## 作者信息

- 姓名：{name}
- 学号：{student_id}
- 院系：{college}
- 专业：{major}
- 指导教师：{advisor}

## 技术栈（含版本线索）

- 后端：
- 前端/小程序：
- 数据库：
- 中间件/第三方：

## 角色与权限

| 角色 | 入口 | 能做什么 | 不能做什么 |
|---|---|---|---|
| 普通用户 |  |  |  |
| 管理员 |  |  |  |

## 功能模块

### 用户端

- 

### 管理端

- 

### 后端业务模块

- 

## 核心业务流程

1. 注册登录：
2. 下单：
3. 支付与状态流转：
4. 取消/回滚：

## 数据库表

| 表名 | 作用 | 关键字段 | 关联 |
|---|---|---|---|
|  |  |  |  |

## 接口清单（核心 3–6 个即可）

| 方法 | 路径 | 用途 | 入参 | 出参 |
|---|---|---|---|---|
|  |  |  |  |  |

## 测试材料

- 已有：
- 缺失：

## 缺证清单

见 `gaps.md`。
"""

GAPS_TEMPLATE = """# 缺证清单

> 凡是源码/材料无法支撑的内容，登记在这里；**不要写进论文正文**。补齐后把状态改为“已补”。

| 编号 | 缺什么 | 影响章节 | 处理方式 | 状态 |
|---|---|---|---|---|
| G-01 | 第五章界面截图 | 5.1–5.2 | 运行系统后截最终态界面 | 待补 |
| G-02 | 测试环境版本号 | 6.2 | 查开发机/依赖版本 | 待补 |
| G-03 | 参考文献清单 | 全篇 | 作者提供或补充可核实文献 | 待补 |
| G-04 | 数据库字段注释 | 4.3.3 | 查建表 SQL/实体类 | 待补 |
"""

README = """# 论文工作区

## 目录

- `manuscript.md`：论文稿（唯一文字源）
- `outline.md`：硬性大纲、图表落位与字数计划
- `paper-context/`：源码证据、图登记表、缺证清单
- `specs/`：标准图规格（JSON，可改文字/模块名）；`entity-attributes.json` 是每个实体的属性清单
- `figs/`：生成的 `.vsdx` 与 `.png`
- `output/`：最终 `.docx` / `.pdf`（提交版 + 可编辑版）

## 命令

```bash
# 1) 扫描源码，产出证据清单
python <skill>/scripts/scan_project.py <项目源码目录> --out paper-context/project-evidence

# 2) 生成/更新标准图（Visio 必须已安装）
python <skill>/scripts/gen_figures.py --spec-dir specs --outdir figs

# 2b) 为每个实体生成一张实体-属性图
python <skill>/scripts/gen_entity_attributes.py --spec specs/entity-attributes.json --outdir figs

# 3) 内容闸门（分章写作阶段加 --draft）
python <skill>/scripts/check_manuscript.py manuscript.md --draft --json output/content-check.json

# 3b) 成稿闸门（正文总字数硬性 12000–16000，不能加 --draft）
python <skill>/scripts/check_manuscript.py manuscript.md --json output/content-check.json

# 4) 生成 docx（提交版：PNG 内嵌）
python <skill>/scripts/build_docx.py manuscript.md --out output/论文_排版前.docx
python <skill>/scripts/paginate_tables.py output/论文_排版前.docx --out output/论文.docx

# 5) 更新目录/页码域并导出 PDF
python <skill>/scripts/update_fields.py output/论文.docx --pdf output/论文.pdf

# 6) docx 结构闸门（提交版）
python <skill>/scripts/check_docx.py output/论文.docx --manuscript manuscript.md

# 7) 可编辑版：第3–4章结构图原位替换为 VSDX OLE
python <skill>/scripts/embed_vsdx.py output/论文.docx --figs figs --out output/论文_可编辑版.docx --pdf output/论文_可编辑版.pdf

# 8) docx 结构闸门（可编辑版）
python <skill>/scripts/check_docx.py output/论文_可编辑版.docx --manuscript manuscript.md
```

> 第五章截图占位在 `manuscript.md` 中以 `![图5.x　题注](PENDING:界面名)` 表示；提交前替换为真实图片路径。
> `figs/` 同时保留 `.vsdx`（可编辑源/可编辑版）和 `.png`（提交版显示图、检视图、兼容兜底），两者都要留。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--title-en", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--student-id", default="")
    ap.add_argument("--college", default="")
    ap.add_argument("--major", default="")
    ap.add_argument("--advisor", default="")
    ap.add_argument("--school", default="河北科技师范学院")
    ap.add_argument("--date", default="", help="已确认的封面日期；不填则留在稿件元数据中，生成 DOCX 前必须补齐")
    ap.add_argument("--tech1", default="Spring Boot框架")
    ap.add_argument("--tech2", default="Vue与Element UI前端技术")
    ap.add_argument("--tech3", default="MyBatis-Plus持久层技术")
    ap.add_argument("--tech4", default="MySQL数据库技术")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.outdir)
    os.makedirs(root, exist_ok=True)
    for sub in ("paper-context", "specs", "figs", "output"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    entities = load_entities()
    all_figures = BASE_FIGURES + entity_figures(entities)

    manuscript = os.path.join(root, "manuscript.md")
    if os.path.exists(manuscript) and not args.force:
        print(f"[new_project] {manuscript} 已存在，未覆盖（--force 可覆盖）")
    else:
        content = MANUSCRIPT.format(
            school=args.school, title=args.title, title_en=args.title_en,
            name=args.name, student_id=args.student_id, college=args.college,
            major=args.major, advisor=args.advisor, date=args.date,
            tech1=args.tech1, tech2=args.tech2, tech3=args.tech3, tech4=args.tech4,
            entity_attr_block=entity_attr_block(entities))
        with open(manuscript, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[new_project] wrote {manuscript}")

    outline = os.path.join(root, "outline.md")
    if not os.path.exists(outline) or args.force:
        figure_rows = "\n".join(f"| {fid} | {title} | {sec} | `specs/{spec}` |"
                                for fid, title, sec, spec in all_figures)
        with open(outline, "w", encoding="utf-8") as f:
            f.write(OUTLINE_TEMPLATE.replace("{figure_rows}", figure_rows))
        print(f"[new_project] wrote {outline}")

    readme = os.path.join(root, "README.md")
    if not os.path.exists(readme) or args.force:
        with open(readme, "w", encoding="utf-8") as f:
            f.write(README)
        print(f"[new_project] wrote {readme}")

    # 复制标准图规格（实体属性图共用一个 entity-attributes.json）
    specs = {spec for _, _, _, spec in all_figures}
    for spec in specs:
        src = os.path.join(SPEC_DIR, spec)
        dst = os.path.join(root, "specs", spec)
        if os.path.exists(src) and (not os.path.exists(dst) or args.force):
            shutil.copy2(src, dst)

    registry = {
        "figures": [
            {
                "id": fid,
                "title": title,
                "section": sec,
                "spec": f"specs/{spec}",
                "output": f"figs/{fid}{title}.png",
                "vsdx": f"figs/{fid}{title}.vsdx",
                "status": "spec_ready",
            }
            for fid, title, sec, spec in all_figures
        ]
    }
    reg_path = os.path.join(root, "paper-context", "figure-registry.json")
    if not os.path.exists(reg_path) or args.force:
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
        print(f"[new_project] wrote {reg_path}")

    spec_path = os.path.join(root, "paper-context", "spec.md")
    if not os.path.exists(spec_path) or args.force:
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(SPEC_TEMPLATE.format(title=args.title, title_en=args.title_en,
                                         name=args.name, student_id=args.student_id,
                                         college=args.college, major=args.major,
                                         advisor=args.advisor))
        print(f"[new_project] wrote {spec_path}")

    gaps_path = os.path.join(root, "paper-context", "gaps.md")
    if not os.path.exists(gaps_path) or args.force:
        with open(gaps_path, "w", encoding="utf-8") as f:
            f.write(GAPS_TEMPLATE)
        print(f"[new_project] wrote {gaps_path}")

    print("[new_project] 完成。下一步：")
    print(f"  python {os.path.join(SKILL_ROOT, 'scripts', 'scan_project.py')} <源码目录> --out {os.path.join(root, 'paper-context', 'project-evidence')}")
    print(f"  python {os.path.join(SKILL_ROOT, 'scripts', 'gen_figures.py')} --spec-dir {os.path.join(root, 'specs')} --outdir {os.path.join(root, 'figs')}")
    print(f"  python {os.path.join(SKILL_ROOT, 'scripts', 'gen_entity_attributes.py')} --spec {os.path.join(root, 'specs', 'entity-attributes.json')} --outdir {os.path.join(root, 'figs')}")


if __name__ == "__main__":
    main()
