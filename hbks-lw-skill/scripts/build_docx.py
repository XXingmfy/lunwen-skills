#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_docx.py —— 把 manuscript.md 生成可提交的中文学位论文 .docx（hbks-lw-skill）

生成结构（6 节，页码独立）：
  节1 封面（无页码）
  节2 原创性声明 + 版权授权书（同页，无页码）
  节3 中文摘要（罗马数字 i 起）
  节4 ABSTRACT（罗马数字续）
  节5 目录（罗马数字续，自动目录域）
  节6 正文至附录（阿拉伯数字 1 起，页眉“XX学院学士学位论文”）

用法：
  python build_docx.py manuscript.md --out 论文.docx [--img-max-width-cm 15]

manuscript.md 约定：
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
header: 河北科技师范学院学士学位论文   # 可选
front_template: assets/已核验前置页.docx # 可选，缺省使用内置模板
---

# 摘　　要
……（一段式摘要）……
关键词：手机租赁；Spring Boot；微信小程序；MySQL

# ABSTRACT
……
Key words: ...

# 目　　录
<!--TOC-->

# 第1章　绪论
## 1.1　研究背景
正文段落，引用写作 [1]。

表4.1　用户表(user)
| 编号 | 字段名 | 类型 | 长度 | 是否非空 | 是否主键 | 注释 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | id | bigint | - | 是 | 是 | 主键ID |

![图4.1　系统总体架构图](figs/图4.1系统总体架构图.png)

第五章截图占位（提交前替换为真实截图）：
![图5.1　用户登录界面](PENDING:用户登录界面)

# 参考文献
[1] 作者. 题名[M]. 出版地: 出版社, 2024.

# 致　　谢
……

# 附　　录
……

也支持：
  <!--PAGEBREAK-->      强制分页
  ![图X.Y　题注](path){width=12cm}   指定图片显示宽度
  - 列表项              简单项目符号
  **加粗文字**          行内加粗

依赖：python-docx>=1.1；PIL 可选（用于按图片比例缩放）。
"""
import argparse
import os
import re
import sys
from frontmatter import front_document

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Twips

# ---------------- 格式基线（与 02-writing-standards.md 一致） ----------------
MARGIN = dict(top=Cm(2.5), bottom=Cm(2.0), left=Cm(2.0), right=Cm(2.0))
GUTTER_TWIPS = 284                 # 0.5 cm 装订线
HEADER_DISTANCE = Cm(1.5)
FOOTER_DISTANCE = Cm(1.75)
BODY_FONT_CN = "宋体"
BODY_FONT_EN = "Times New Roman"
HEADING_FONT_CN = "黑体"
BODY_SIZE_PT = 12                  # 小四
LINE_EXACT_PT = 20                 # 固定 20 磅
FIRST_LINE_CHARS = 2

DECLARATION_TITLE = "学位论文原创性声明"
AUTHORIZATION_TITLE = "学位论文版权使用授权书"

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*(?:\{width=([\d.]+)\s*cm\})?\s*$")
CAPTION_TABLE_RE = re.compile(r"^(?:续表|表)\s*\d+\.\d+")


# ---------------- 低层 OOXML ----------------
def set_run(run, cn=BODY_FONT_CN, en=BODY_FONT_EN, size=BODY_SIZE_PT,
            bold=False, italic=False, superscript=False, color=None, underline=False):
    run.font.name = en
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.underline = underline
    run.font.color.rgb = RGBColor(0, 0, 0) if color is None else color
    if superscript:
        run.font.superscript = True
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), en)
    rFonts.set(qn("w:hAnsi"), en)
    rFonts.set(qn("w:eastAsia"), cn)


def set_para(p, align=None, indent_chars=0, line_exact=None, before=None, after=None,
             keep_next=False):
    pf = p.paragraph_format
    if align is not None:
        p.alignment = align
    if indent_chars:
        pPr = p._p.get_or_add_pPr()
        ind = pPr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            pPr.append(ind)
        ind.set(qn("w:firstLineChars"), str(int(indent_chars * 100)))
        ind.set(qn("w:firstLine"), str(int(indent_chars * BODY_SIZE_PT * 20)))
    if line_exact:
        pf.line_spacing_rule = 3      # exactly
        pf.line_spacing = Pt(line_exact)
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if keep_next:
        pf.keep_with_next = True


def add_runs_with_inline(p, text, cn=BODY_FONT_CN, en=BODY_FONT_EN, size=BODY_SIZE_PT,
                         base_bold=False):
    """支持 **加粗**、`代码`、[n] 上标引用。"""
    tokens = re.split(r"(\*\*.+?\*\*|`[^`]+`|\[\d+(?:[-–]\d+)?\])", text)
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            set_run(r, cn=cn, en=en, size=size, bold=True)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            r = p.add_run(tok[1:-1])
            set_run(r, cn="宋体", en="Consolas", size=size - 1)
        elif re.fullmatch(r"\[\d+(?:[-–]\d+)?\]", tok):
            r = p.add_run(tok)
            set_run(r, cn=cn, en=en, size=size, bold=base_bold, superscript=True)
        else:
            r = p.add_run(tok)
            set_run(r, cn=cn, en=en, size=size, bold=base_bold)


def norm(t):
    return t.replace("\u3000", "").replace(" ", "")


def set_section_margins(section):
    section.top_margin = MARGIN["top"]
    section.bottom_margin = MARGIN["bottom"]
    section.left_margin = MARGIN["left"]
    section.right_margin = MARGIN["right"]
    try:
        section.gutter = Twips(GUTTER_TWIPS)
    except Exception:
        pass
    section.header_distance = HEADER_DISTANCE
    section.footer_distance = FOOTER_DISTANCE


def _fld(run, fldchar_type=None):
    el = OxmlElement("w:fldChar")
    if fldchar_type:
        el.set(qn("w:fldCharType"), fldchar_type)
    run._element.append(el)


def add_page_field(paragraph):
    r = paragraph.add_run(); _fld(r, "begin")
    r = paragraph.add_run()
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = " PAGE "
    r._element.append(it)
    r = paragraph.add_run(); _fld(r, "separate")
    r = paragraph.add_run("1"); set_run(r, size=9)
    r = paragraph.add_run(); _fld(r, "end")


def add_front_heading(doc, text):
    """摘要/ABSTRACT/目录标题：外观同一级标题，但不进入自动目录。"""
    from docx.enum.style import WD_STYLE_TYPE
    name = "Front Heading"
    try:
        st = doc.styles[name]
    except KeyError:
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles["Normal"]
        st.font.name = BODY_FONT_EN
        st.font.size = Pt(15)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)
        rPr = st.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts"); rPr.append(rFonts)
        rFonts.set(qn("w:ascii"), BODY_FONT_EN)
        rFonts.set(qn("w:hAnsi"), BODY_FONT_EN)
        rFonts.set(qn("w:eastAsia"), HEADING_FONT_CN)
        pf = st.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.space_before = Pt(12)
        pf.space_after = Pt(12)
        pPr = st.element.get_or_add_pPr()
        ol = OxmlElement("w:outlineLvl")
        ol.set(qn("w:val"), "9")
        pPr.append(ol)
    p = doc.add_paragraph(style=st)
    add_runs_with_inline(p, text, cn=HEADING_FONT_CN, size=15, base_bold=True)
    return p


def add_toc_field(doc):
    p = doc.add_paragraph()
    r = p.add_run(); _fld(r, "begin")
    r = p.add_run()
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = ' TOC \\o "1-3" \\h \\z \\u '
    r._element.append(it)
    r = p.add_run(); _fld(r, "separate")
    r = p.add_run("（目录为自动域：请在 Word 中全选后按 F9 更新；生成脚本也可自动更新）")
    set_run(r, size=10.5, color=RGBColor(0x80, 0x80, 0x80))
    r = p.add_run(); _fld(r, "end")


def enable_update_fields(doc):
    settings = doc.settings.element
    uf = settings.find(qn("w:updateFields"))
    if uf is None:
        uf = OxmlElement("w:updateFields")
        settings.append(uf)
    uf.set(qn("w:val"), "true")


def set_pgnum(section, fmt=None, start=None):
    sectPr = section._sectPr
    pg = sectPr.find(qn("w:pgNumType"))
    if pg is None:
        pg = OxmlElement("w:pgNumType")
        sectPr.append(pg)
    if fmt:
        pg.set(qn("w:fmt"), fmt)
    if start is not None:
        pg.set(qn("w:start"), str(start))
    else:
        # 续排：必须删掉从上一节复制来的 w:start，否则每节都从 1 重新编号
        if pg.get(qn("w:start")) is not None:
            del pg.attrib[qn("w:start")]


def new_section(doc, fmt=None, start=None, header=None):
    s = doc.add_section(WD_SECTION_START.NEW_PAGE)
    set_section_margins(s)
    s.header.is_linked_to_previous = False
    s.footer.is_linked_to_previous = False
    for p in list(s.header.paragraphs):
        p.text = ""
    for p in list(s.footer.paragraphs):
        p.text = ""
    if fmt:
        set_pgnum(s, fmt=fmt, start=start)
        fp = s.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_page_field(fp)
    if header:
        hp = s.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(hp.add_run(header), size=9)
    return s


# 前置页统一由 frontmatter.py 绑定核验模板，不再保留旧空段落拼接实现。

# ---------------- 正文元素 ----------------
def add_heading(doc, level, text, page_break=False):
    style = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}.get(level, "Heading 3")
    p = doc.add_paragraph(style=style)
    size = {1: 15, 2: 14, 3: 13}[level]
    add_runs_with_inline(p, text, cn=HEADING_FONT_CN, size=size,
                         base_bold=(level in (1, 3)))
    if level == 1:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_before = Pt(12)
        pf.space_after = Pt(12)
        if page_break:
            pf.page_break_before = True
    elif level == 2:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
    return p


def _set_cell_text(cell, text, bold=False, size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    add_runs_with_inline(p, text, size=size, base_bold=bold)


def add_three_line_table(doc, header, rows, caption=None):
    if caption:
        cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para(cp, before=6, after=3, keep_next=True)
        set_run(cp.add_run(caption), size=10.5)
    n_cols = max([len(header)] + [len(r) for r in rows]) if rows else len(header)
    table = doc.add_table(rows=1 + len(rows), cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for ri, rowdata in enumerate([header] + rows):
        for ci in range(n_cols):
            txt = rowdata[ci].strip() if ci < len(rowdata) else ""
            _set_cell_text(table.cell(ri, ci), txt, bold=(ri == 0))
    # 三线表边框
    tblPr = table._tbl.tblPr
    for el in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(el)
    borders = OxmlElement("w:tblBorders")
    for edge, sz, val in (("top", "12", "single"), ("bottom", "12", "single"),
                          ("left", "", "nil"), ("right", "", "nil"),
                          ("insideH", "", "nil"), ("insideV", "", "nil")):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), val)
        if sz:
            e.set(qn("w:sz"), sz); e.set(qn("w:space"), "0"); e.set(qn("w:color"), "000000")
        borders.append(e)
    tblPr.append(borders)
    # 栏目线：表头行下边框
    for tc in table.rows[0]._tr.findall(qn("w:tc")):
        tcPr = tc.get_or_add_tcPr()
        tcB = OxmlElement("w:tcBorders")
        b = OxmlElement("w:bottom")
        b.set(qn("w:val"), "single"); b.set(qn("w:sz"), "6")
        b.set(qn("w:space"), "0"); b.set(qn("w:color"), "000000")
        tcB.append(b); tcPr.append(tcB)
    # 表头跨页重复 + 行内不断页
    trPr = table.rows[0]._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader"); th.set(qn("w:val"), "true"); trPr.append(th)
    for row in table.rows:
        trPr = row._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit"); cs.set(qn("w:val"), "true"); trPr.append(cs)
    # 整表与题注同页；超过一页的表由 paginate_tables.py 按 Word 实测拆续表。
    for ri, row in enumerate(table.rows):
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.keep_together = True
                p.paragraph_format.keep_with_next = ri < len(table.rows) - 1
    if caption and caption.startswith('续表'):
        cp.paragraph_format.page_break_before = True
    # 表后留白
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def _dashed_box(doc, label, width_cm=14.0, height_cm=5.0):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    cell.width = Cm(width_cm)
    row = table.rows[0]
    row.height = Cm(height_cm)
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(f"此处插入「{label}」界面截图"), size=10.5, color=RGBColor(0x80, 0x80, 0x80))
    p2 = cell.add_paragraph(); p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p2.add_run("（提交前替换为最终运行界面）"), size=9, color=RGBColor(0x99, 0x99, 0x99))
    # 虚线边框
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "dashed"); e.set(qn("w:sz"), "6")
        e.set(qn("w:space"), "0"); e.set(qn("w:color"), "808080")
        borders.append(e)
    tblPr.append(borders)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_image(doc, alt, raw_path, img_max_cm, base_dir, width_override=None):
    path = raw_path.strip()
    is_pending = path.startswith("PENDING")
    if is_pending:
        label = path.split(":", 1)[1].strip() if ":" in path else alt
        _dashed_box(doc, label, width_cm=img_max_cm)
        if alt:
            cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_para(cp, before=0, after=6)
            set_run(cp.add_run(alt), size=10.5)
        return
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    if not os.path.exists(path):
        _dashed_box(doc, f"缺图：{os.path.basename(path)}", width_cm=img_max_cm, height_cm=3.5)
        if alt:
            cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_run(cp.add_run(alt), size=10.5)
        return
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    width_cm = float(width_override) if width_override else img_max_cm
    max_h_cm = 18.0
    try:
        from PIL import Image
        im = Image.open(path)
        w, h = im.size
        width_cm = min(width_cm, max_h_cm * w / h)
    except Exception:
        pass
    inline = p.add_run().add_picture(path, width=Cm(width_cm))
    # 把题注写进图片替代文字（descr），供后续 VSDX 可编辑版按图号精确匹配
    try:
        docPr = inline._inline.docPr
        docPr.set("descr", alt or os.path.basename(path))
        docPr.set("title", alt or os.path.basename(path))
    except Exception:
        pass
    if alt:
        cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para(cp, before=0, after=6)
        set_run(cp.add_run(alt), size=10.5)


# ---------------- Markdown 解析 ----------------
def parse_front_matter(lines):
    meta = {}
    if not lines or lines[0].strip() != "---":
        return meta, lines
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return meta, lines
    for line in lines[1:end]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, lines[end + 1:]


def iter_blocks(lines):
    i, n = 0, len(lines)
    in_ref = False
    in_comment = False
    while i < n:
        line = lines[i].strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            i += 1
            continue
        if not line:
            i += 1
            continue
        if line in ("<!--TOC-->", "<!-- toc -->"):
            yield ("toc",)
            i += 1
            continue
        if line in ("<!--PAGEBREAK-->", "<!-- pagebreak -->"):
            yield ("pagebreak",)
            i += 1
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            i += 1          # 写作提示/内部注释不进入正文
            continue
        m = HEADING_RE.match(line)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            in_ref = "参考文献" in norm(text)
            yield ("h", level, text)
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            yield ("table", header, rows)
            continue
        mi = IMG_RE.match(line)
        if mi:
            yield ("img", mi.group(1), mi.group(2), mi.group(3))
            i += 1
            continue
        if in_ref and re.match(r"^\[\d+\]\s*\S", line):
            yield ("ref", line)
            i += 1
            continue
        if in_ref:
            yield ("ref_cont", line)
            i += 1
            continue
        if line.startswith("- ") or line.startswith("* "):
            yield ("li", line[2:].strip())
            i += 1
            continue
        yield ("p", line)
        i += 1


# ---------------- 主流程 ----------------
def build_docx(manuscript_path, out_path, img_max_cm):
    base_dir = os.path.dirname(os.path.abspath(manuscript_path))
    with open(manuscript_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    meta, rest = parse_front_matter(lines)

    doc = front_document(meta, base_dir)
    # 样式兜底
    for sname in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title"):
        try:
            st = doc.styles[sname]
            st.font.color.rgb = RGBColor(0, 0, 0)
        except KeyError:
            continue
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT_EN
    normal.font.size = Pt(BODY_SIZE_PT)
    if normal.element.rPr is not None and normal.element.rPr.rFonts is not None:
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT_CN)
    for sname, (cn, pt, bold) in {
        "Heading 1": (HEADING_FONT_CN, 15, True),
        "Heading 2": (HEADING_FONT_CN, 14, False),
        "Heading 3": (HEADING_FONT_CN, 13, True),
    }.items():
        try:
            st = doc.styles[sname]
            st.font.name = BODY_FONT_EN
            st.font.size = Pt(pt)
            st.font.bold = bold
            st.font.color.rgb = RGBColor(0, 0, 0)
            rPr = st.element.get_or_add_rPr()
            rFonts = rPr.find(qn("w:rFonts"))
            if rFonts is None:
                rFonts = OxmlElement("w:rFonts"); rPr.append(rFonts)
            rFonts.set(qn("w:ascii"), BODY_FONT_EN)
            rFonts.set(qn("w:hAnsi"), BODY_FONT_EN)
            rFonts.set(qn("w:eastAsia"), cn)
        except KeyError:
            pass

    # 封面及声明授权页已从已核验模板绑定，禁止再次按空段落重建。

    body_started = False
    just_started_section = False
    pending_table_caption = None
    blocks = list(iter_blocks(rest))
    idx = 0
    while idx < len(blocks):
        blk = blocks[idx]
        kind = blk[0]
        if kind == "h":
            level, text = blk[1], blk[2]
            nt = norm(text)
            front_heading = False
            if level == 1:
                if (nt.startswith("摘要") or nt.startswith("中文摘要")) and not body_started:
                    new_section(doc, "lowerRoman", start=1)
                    just_started_section = True
                    front_heading = True
                elif nt.upper().startswith("ABSTRACT"):
                    new_section(doc, "lowerRoman")
                    just_started_section = True
                    front_heading = True
                elif "目录" in nt:
                    new_section(doc, "lowerRoman")
                    just_started_section = True
                    front_heading = True
                elif nt.startswith("第") and "章" in nt and not body_started:
                    header = meta.get("header") or f"{meta.get('school', '河北科技师范学院')}学士学位论文"
                    new_section(doc, "decimal", start=1, header=header)
                    body_started = True
                    just_started_section = True
            if front_heading:
                add_front_heading(doc, text)
            else:
                add_heading(doc, level, text, page_break=(level == 1 and not just_started_section))
            just_started_section = False
        elif kind == "toc":
            has_toc_heading = any(b[0] == "h" and b[1] == 1 and "目录" in norm(b[2])
                                  for b in blocks[:idx])
            if not has_toc_heading:
                new_section(doc, "lowerRoman")
                add_heading(doc, 1, "目　　录")
                just_started_section = False
            add_toc_field(doc)
        elif kind == "p":
            text = blk[1]
            if CAPTION_TABLE_RE.match(text):
                pending_table_caption = text
                idx += 1
                continue
            # 图前引导句与图片同页：下一块是图片时设置“与下段同页”
            next_is_img = (idx + 1 < len(blocks) and blocks[idx + 1][0] == "img")
            p = doc.add_paragraph()
            set_para(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_chars=FIRST_LINE_CHARS,
                     line_exact=LINE_EXACT_PT, before=0, after=0, keep_next=next_is_img)
            add_runs_with_inline(p, text)
        elif kind == "li":
            p = doc.add_paragraph()
            set_para(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY, line_exact=LINE_EXACT_PT, before=0, after=0)
            p.paragraph_format.left_indent = Cm(0.74)
            p.paragraph_format.first_line_indent = Cm(-0.37)
            add_runs_with_inline(p, "· " + blk[1])
        elif kind == "table":
            add_three_line_table(doc, blk[1], blk[2], pending_table_caption)
            pending_table_caption = None
        elif kind == "img":
            add_image(doc, blk[1], blk[2], img_max_cm, base_dir, blk[3])
        elif kind == "ref":
            p = doc.add_paragraph()
            set_para(p, line_exact=LINE_EXACT_PT, before=0, after=0)
            p.paragraph_format.left_indent = Pt(21)
            p.paragraph_format.first_line_indent = Pt(-21)
            add_runs_with_inline(p, blk[1], size=10.5)
        elif kind == "ref_cont":
            if doc.paragraphs:
                add_runs_with_inline(doc.paragraphs[-1], blk[1], size=10.5)
        elif kind == "pagebreak":
            doc.add_page_break()
        idx += 1

    # 文档属性
    cp = doc.core_properties
    cp.title = meta.get("title", "")
    cp.author = meta.get("name", "")
    cp.subject = meta.get("doc_type", "学士学位论文")
    cp.comments = ""
    enable_update_fields(doc)
    doc.save(out_path)
    print(f"[build_docx] wrote {out_path}")
    print("[build_docx] 下一步：先运行 paginate_tables.py --out 论文.docx，再 update_fields.py --pdf 论文.pdf 并 check_docx.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manuscript")
    ap.add_argument("--out", default="论文.docx")
    ap.add_argument("--img-max-width-cm", type=float, default=15.0)
    args = ap.parse_args()
    build_docx(args.manuscript, args.out, args.img_max_width_cm)


if __name__ == "__main__":
    main()
