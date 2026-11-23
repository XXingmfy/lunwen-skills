#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_docx.py —— docx 结构闸门（build_docx / update_fields 之后运行）

检查：
  - 分节数量与页码格式（封面/声明无页码；摘要罗马；正文阿拉伯）
  - 正文页眉、页脚 PAGE 域、自动目录 TOC 域
  - 标题样式（Heading 1/2/3）与字号
  - 三线表边框、表头跨页重复
  - 图片数量/宽度、截图占位数量
  - 未完成措辞残留、文档属性

用法：
  python check_docx.py 论文.docx [--manuscript manuscript.md] [--json report.json]
  # 可编辑版（VSDX OLE）：自动识别并核对 embeddings 数量 / EMF 预览
退出码：0=通过（可能有警告），1=存在阻断问题。
"""
import argparse
import json
import re
import sys
import zipfile
import hashlib
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


def qn_attr(el, attr):
    return el.get(qn(attr)) if el is not None else None


def section_pgnum(section):
    sectPr = section._sectPr
    pg = sectPr.find(qn("w:pgNumType"))
    if pg is None:
        return None, None
    return pg.get(qn("w:fmt")), pg.get(qn("w:start"))


def has_field(container, field_name):
    try:
        xml = container._element.xml
    except Exception:
        return False
    return field_name in xml and "fldChar" in xml


def table_borders(tbl):
    tblPr = tbl._tbl.tblPr
    b = tblPr.find(qn("w:tblBorders"))
    if b is None:
        return {}
    out = {}
    for edge in ("top", "bottom", "left", "right", "insideH", "insideV"):
        e = b.find(qn(f"w:{edge}"))
        if e is not None:
            out[edge] = e.get(qn("w:val"))
    return out


def has_header_repeat(tbl):
    if not tbl.rows:
        return False
    trPr = tbl.rows[0]._tr.find(qn("w:trPr"))
    return trPr is not None and trPr.find(qn("w:tblHeader")) is not None


def check(path, manuscript=None, layout_report=None):
    doc = Document(path)
    errors, warnings, info = [], [], []

    # ---------- 分节与页码 ----------
    n_sec = len(doc.sections)
    info.append(f"分节数：{n_sec}")
    if n_sec < 6:
        errors.append(f"分节数不足（{n_sec}），应为 6 节：封面/声明/中文摘要/英文摘要/目录/正文")
    if n_sec >= 6:
        expected = [(2, "lowerRoman", "1"), (3, "lowerRoman", None),
                    (4, "lowerRoman", None), (5, "decimal", "1")]
        for idx, fmt, start in expected:
            actual_fmt, actual_start = section_pgnum(doc.sections[idx])
            # OOXML 中 w:fmt 缺省即 decimal，Word 保存时可能省略该属性
            fmt_ok = (actual_fmt == fmt) or (fmt == "decimal" and actual_fmt is None)
            if not fmt_ok:
                errors.append(f"第 {idx+1} 节页码格式为 {actual_fmt}，应为 {fmt}")
            if start and actual_start != start:
                errors.append(f"第 {idx+1} 节页码起始为 {actual_start}，应为 {start}")
        for idx in (0, 1):
            fmt, _ = section_pgnum(doc.sections[idx])
            if fmt:
                errors.append(f"第 {idx+1} 节（封面/声明）不应设置页码")
            foot = doc.sections[idx].footer
            if has_field(foot, "PAGE"):
                errors.append(f"第 {idx+1} 节页脚不应包含 PAGE 域")
        header_text = doc.sections[5].header.paragraphs[0].text.strip() if doc.sections[5].header.paragraphs else ""
        if "学士学位论文" not in header_text:
            errors.append(f"正文页眉缺少“学士学位论文”（当前：{header_text or '空'}）")
        else:
            info.append(f"正文页眉：{header_text}")
        if not has_field(doc.sections[5].footer, "PAGE"):
            errors.append("正文页脚缺少 PAGE 域")
    # 页边距
    s0 = doc.sections[0]
    info.append(f"页边距：上 {s0.top_margin.cm:.1f} 下 {s0.bottom_margin.cm:.1f} "
                f"左 {s0.left_margin.cm:.1f} 右 {s0.right_margin.cm:.1f} cm")

    # ---------- 样式 ----------
    style_expect = {"Normal": (12, "宋体"), "Heading 1": (15, "黑体"),
                    "Heading 2": (14, "黑体"), "Heading 3": (13, "黑体")}
    for name, (pt, cn) in style_expect.items():
        try:
            st = doc.styles[name]
        except KeyError:
            errors.append(f"缺少样式：{name}")
            continue
        size = st.font.size.pt if st.font.size else None
        if size and abs(size - pt) > 0.2:
            warnings.append(f"样式 {name} 字号 {size}pt，基线为 {pt}pt")
        rPr = st.element.find(qn("w:rPr"))
        ea = None
        if rPr is not None:
            rf = rPr.find(qn("w:rFonts"))
            if rf is not None:
                ea = rf.get(qn("w:eastAsia"))
        if ea and ea != cn:
            warnings.append(f"样式 {name} 中文字体为 {ea}，基线为 {cn}")

    # ---------- 标题与目录 ----------
    h1 = [p.text.strip() for p in doc.paragraphs if p.style.name == "Heading 1"]
    h2 = [p.text.strip() for p in doc.paragraphs if p.style.name == "Heading 2"]
    h3 = [p.text.strip() for p in doc.paragraphs if p.style.name == "Heading 3"]
    info.append(f"标题：一级 {len(h1)} 个，二级 {len(h2)} 个，三级 {len(h3)} 个")
    if len(h1) < 10:
        warnings.append(f"一级标题仅 {len(h1)} 个，检查是否漏章/未使用标题样式")
    xml = doc.element.xml
    if "TOC \\" not in xml and "TOC\\" not in xml:
        errors.append("未找到自动目录 TOC 域（目录可能是手打的）")
    else:
        info.append("自动目录 TOC 域：存在")

    # ---------- 表格 ----------
    n_tables = len(doc.tables)
    bad_borders, no_repeat = [], []
    for i, t in enumerate(doc.tables):
        b = table_borders(t)
        txt = "".join(c.text for r in t.rows[:1] for c in r.cells)
        if "此处插入" in txt:
            continue
        if b.get("top") != "single" or b.get("bottom") != "single":
            bad_borders.append(i)
        if any(b.get(edge) not in (None, "nil", "none") for edge in ('left','right','insideV','insideH')):
            bad_borders.append(i)
        # 必须核验栏目线、单元格边框覆盖与行断页属性，不能只看 tblBorders。
        for ci, cell in enumerate(t.rows[0].cells):
            cb=cell._tc.get_or_add_tcPr().find(qn('w:tcBorders'))
            edge=cb.find(qn('w:bottom')) if cb is not None else None
            if edge is None or edge.get(qn('w:val'))!='single': bad_borders.append(i)
        for ri,row in enumerate(t.rows):
            flag=row._tr.get_or_add_trPr().find(qn('w:cantSplit'))
            if flag is None or flag.get(qn('w:val')) in ('0','false','off'):
                errors.append(f'表 {i+1} 第 {ri+1} 行未禁止行内断页')
            for cell in row.cells:
                cb=cell._tc.get_or_add_tcPr().find(qn('w:tcBorders'))
                if cb is not None:
                    for edge in cb:
                        tag=edge.tag.split('}')[-1]
                        if tag in ('left','right','insideH','insideV') and edge.get(qn('w:val')) not in ('nil','none'):
                            bad_borders.append(i)
                        if tag=='top' and ri>0 and edge.get(qn('w:val')) not in ('nil','none'):
                            bad_borders.append(i)
                        if tag=='bottom' and ri not in (0,len(t.rows)-1) and edge.get(qn('w:val')) not in ('nil','none'):
                            bad_borders.append(i)
        if not has_header_repeat(t):
            no_repeat.append(i)
    info.append(f"表格：{n_tables} 个")
    if bad_borders:
        errors.append(f"以下表格不是标准三线表（第 {bad_borders[:8]} 个）")
    if no_repeat:
        errors.append(f"以下表格未设置重复表头（索引 {no_repeat[:8]}）")

    # ---------- 图片 / VSDX OLE 与截图占位 ----------
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        embeddings = [n for n in names
                      if n.startswith("word/embeddings/") and n.lower().endswith(".vsdx")]
        emf_previews = [n for n in names
                        if n.startswith("word/media/") and n.lower().endswith(".emf")]
    editable = bool(embeddings)
    widths = [sh.width.cm for sh in doc.inline_shapes]
    placeholder = sum(1 for t in doc.tables
                      if "此处插入" in "".join(c.text for r in t.rows[:1] for c in r.cells))

    if editable:
        info.append(f"可编辑版：VSDX OLE {len(embeddings)} 个，EMF 预览 {len(emf_previews)} 个")
        if emf_previews and len(emf_previews) < len(embeddings):
            warnings.append("EMF 预览数量少于 VSDX OLE 数量，非 Visio 环境可能显示不全")
        if manuscript:
            with open(manuscript, "r", encoding="utf-8") as f:
                text = f.read()
            struct_imgs = re.findall(r"^!\[(图\s*([34])\.\d+[^\]]*)\]\(([^)]+)\)",
                                     text, flags=re.M)
            pending_struct = [x for x in struct_imgs if "PENDING" in x[2]]
            expected = len(struct_imgs) - len(pending_struct)
            if len(embeddings) != expected:
                warnings.append(
                    f"稿件中第3–4章结构图 {expected} 张，docx 中 VSDX OLE {len(embeddings)} 个，请核对")
            elif expected:
                info.append(f"结构图 VSDX OLE 覆盖：{len(embeddings)}/{expected} 张（一致）")
    else:
        info.append(f"图片：{len(widths)} 张" + (f"，宽度 {min(widths):.1f}–{max(widths):.1f} cm" if widths else ""))
        if widths and max(widths) > 15.5:
            warnings.append(f"存在宽度 {max(widths):.1f} cm 的图片，可能撑出版心（建议 ≤14–15 cm）")
        if manuscript:
            with open(manuscript, "r", encoding="utf-8") as f:
                text = f.read()
            md_imgs = len(re.findall(r"^!\[", text, flags=re.M))
            md_pending = len(re.findall(r"\]\(\s*PENDING", text, flags=re.M))
            md_real = md_imgs - md_pending
            content_images=sum(1 for shape in doc.inline_shapes
                               if shape._inline.docPr.get('descr','')!='学校LOGO')
            if md_real != content_images:
                warnings.append(f"稿件中实际图片 {md_real} 张，docx 正文图 {content_images} 张（排除模板校徽；另有 {md_pending} 处占位）")

    if placeholder:
        errors.append(f"有 {placeholder} 处界面截图占位待替换，禁止交付")

    # ---------- 文本残留 ----------
    # 覆盖表格、文本框、页眉页脚，避免占位词藏在非正文 story 中。
    with zipfile.ZipFile(path) as package:
        from lxml import etree
        full_text='\n'.join(''.join(etree.fromstring(package.read(n)).itertext())
                            for n in package.namelist()
                            if n=='word/document.xml' or re.match(r'word/(header|footer)\d+\.xml$',n))
    for w in ("待补充", "待完善", "TBD", "TODO", "初稿", "后续完善", "根据源码", "从源码", "{{", "【待", "此处插入", "点击此处输入", "占位框"):
        if w in full_text:
            errors.append(f"docx 正文仍存在“{w}”")
    if not doc.core_properties.title:
        warnings.append("文档属性缺少标题")
    if doc.core_properties.author in ("", "Administrator", "user"):
        warnings.append(f"文档属性作者为“{doc.core_properties.author}”，建议改为作者姓名")
    else:
        info.append(f"文档属性作者：{doc.core_properties.author}")

    layout_path=Path(layout_report) if layout_report else Path(path).with_suffix('.layout.json')
    if not layout_path.exists():
        errors.append('缺少 Word 实际分页报告；运行 update_fields.py 生成 .layout.json，OOXML 检查不能代替分页验收')
    else:
        layout=json.loads(layout_path.read_text(encoding='utf-8'))
        if layout.get('docx_sha256')!=hashlib.sha256(Path(path).read_bytes()).hexdigest():
            errors.append('分页报告已过期（DOCX 已变化），请对最终文件重跑 Word 更新/分页验收')
        if layout.get('engine')!='Microsoft Word' or not layout.get('ok'):
            errors.append('Word 版面闸门未通过：'+'；'.join(layout.get('errors',[])))
        if any(layout.get('front',{}).get(k)!=[2,2] for k in ('学位论文原创性声明','学位论文版权使用授权书')):
            errors.append('分页报告未完成当前前置页模板验收；--tables-only 不能用于论文提交')
        if layout.get('ok'): info.append('Word 实际分页：整表/续表、题注同页、行不截断检查通过')
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "stats": {"sections": n_sec, "tables": n_tables, "images": len(widths),
                  "vsdx_embeddings": len(embeddings), "editable": editable,
                  "placeholders": placeholder,
                  "headings": {"h1": len(h1), "h2": len(h2), "h3": len(h3)}},
    }
    return result


def print_report(result):
    print("=" * 68)
    print("docx 结构闸门")
    print("=" * 68)
    for s in result["info"]:
        print("  ·", s)
    if result["errors"]:
        print(f"\n阻断问题（{len(result['errors'])}）：")
        for e in result["errors"]:
            print("  [ERROR]", e)
    if result["warnings"]:
        print(f"\n警告（{len(result['warnings'])}）：")
        for w in result["warnings"]:
            print("  [WARN ]", w)
    print("\n结论：" + ("通过（有警告）" if result["ok"] else "未通过，请先修复阻断问题"))
    print("=" * 68)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--manuscript", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--layout-report", default=None)
    args = ap.parse_args()
    result = check(args.docx, args.manuscript, args.layout_report)
    print_report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    ok = result["ok"] and (not args.strict or not result["warnings"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
