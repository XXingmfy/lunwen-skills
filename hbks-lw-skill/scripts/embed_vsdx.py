#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_vsdx.py —— 生成“可编辑版”论文 docx：把结构图原位替换成 VSDX OLE 对象

背景（为什么不是直接插 vsdx 就完事）：
  - Word 里的 VSDX 不是普通图片，而是 OLE 对象；Word 显示的是对象自带的 EMF 预览，
    双击可进 Visio 编辑，导出 PDF 时是矢量。
  - python-docx 不支持 OLE，必须用 Word COM 后处理。
  - 直接 AddOLEObject(Range=图片.Range) 在长文档里会把对象插到文档开头（实测），
    必须用 doc.Range(pos, pos).InlineShapes.AddOLEObject(...) 在零长度位置插入，
    且要“先插新对象、再删旧图片”，并从后往前处理，位置才不会乱。

输入：build_docx.py 生成的 PNG 版 docx（图片替代文字 = 图题注，如“图4.1　系统总体设计流程图”）
      以及 figs/ 下的同名 .vsdx。

输出：output/论文_可编辑版.docx（结构图 = VSDX OLE，截图 = 原 PNG）
      可选 --pdf 同时更新目录/页码域并导出 PDF。

用法：
  python embed_vsdx.py output/论文.docx --figs figs --out output/论文_可编辑版.docx
  python embed_vsdx.py output/论文.docx --figs figs --out output/论文_可编辑版.docx --pdf output/论文_可编辑版.pdf

说明：
  - 只替换题注以“图3.x / 图4.x”等结构图编号开头的图片；第 5 章界面截图（图5.x）没有 vsdx，
    会保留 PNG，这是预期行为。
  - 封面校徽等无“图X.Y”题注的图片不会被替换。
  - 找不到对应 vsdx 的图会保留 PNG 并列在报告里，不会静默丢失。
"""
import argparse
import glob
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from office_prepare import prepare_office

FIG_ID_RE = re.compile(r"^\s*(图\s*\d+\.\d+)")
STRUCT_CHAPTERS = {"3", "4"}          # 只有第 3–4 章是 Visio 结构图


def find_vsdx(figs_dir, fig_id):
    """按“图4.1”精确匹配文件名，避免图4.1误配到图4.10。"""
    num = fig_id.replace("图", "").replace(" ", "")
    pattern = re.compile(r"^图\s*" + re.escape(num) + r"(?!\d)")
    for path in glob.glob(os.path.join(figs_dir, "*.vsdx")):
        name = os.path.splitext(os.path.basename(path))[0]
        if pattern.match(name):
            return path
    return None


def embed(docx_path, figs_dir, out_path, make_pdf=None, structure_only=True):
    docx_path = os.path.abspath(docx_path)
    figs_dir = os.path.abspath(figs_dir)
    out_path = os.path.abspath(out_path)
    if docx_path == out_path:
        raise SystemExit("[embed_vsdx] --out 不能与输入 docx 相同；请输出到新文件，保留提交版")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # Word 启动与重排会读默认打印机来算版面；临时切到本地虚拟打印机，
    # 避免每次自动化都去探测网络打印机（退出时自动恢复原设置）。
    with prepare_office():
        return _embed_with_word(docx_path, figs_dir, out_path, make_pdf, structure_only)


def _embed_with_word(docx_path, figs_dir, out_path, make_pdf, structure_only):
    import win32com.client

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    try:
        word.DisplayAlerts = 0
    except Exception:
        pass

    doc = None
    replaced, kept_png, skipped = [], [], []
    try:
        doc = word.Documents.Open(docx_path, ReadOnly=False, AddToRecentFiles=False)
        total = doc.InlineShapes.Count
        print(f"[embed_vsdx] 打开 {os.path.basename(docx_path)}，内嵌图形 {total} 个")

        for i in range(total, 0, -1):
            shp = doc.InlineShapes(i)
            try:
                alt = (shp.AlternativeText or "").strip()
            except Exception:
                alt = ""
            m = FIG_ID_RE.match(alt)
            if not m:
                skipped.append((i, alt or "(无题注)", "非结构图（封面/截图等）"))
                continue
            fig_id = m.group(1).replace(" ", "")
            chapter = fig_id.replace("图", "").split(".")[0]
            if structure_only and chapter not in STRUCT_CHAPTERS:
                kept_png.append((fig_id, alt, "非第3–4章结构图"))
                continue
            vsdx = find_vsdx(figs_dir, fig_id)
            if not vsdx:
                kept_png.append((fig_id, alt, "figs/ 下找不到同名 vsdx"))
                continue

            pos = shp.Range.Start
            w, h = shp.Width, shp.Height
            try:
                new = None
                last_err = None
                for class_type in ("Visio.Drawing.15", "Visio.Drawing.14",
                                   "Visio.Drawing.12", "Visio.Drawing"):
                    try:
                        rng = doc.Range(pos, pos)
                        new = rng.InlineShapes.AddOLEObject(
                            ClassType=class_type, FileName=vsdx,
                            LinkToFile=False, DisplayAsIcon=False)
                        break
                    except Exception as ex:
                        last_err = ex
                if new is None:
                    raise last_err or RuntimeError("无法创建 Visio OLE 对象")
                new.LockAspectRatio = False
                new.Width = w
                new.Height = h
                try:
                    new.AlternativeText = alt
                except Exception:
                    pass
                shp.Range.Delete()
                replaced.append((fig_id, alt, os.path.basename(vsdx), round(w, 1), round(h, 1)))
            except Exception as ex:
                kept_png.append((fig_id, alt, f"替换失败：{str(ex)[:120]}"))

        doc.Repaginate()
        if os.path.exists(out_path):
            os.remove(out_path)
        doc.SaveAs(out_path)
        try:
            print(f"[embed_vsdx] 可编辑版总页数：{doc.ComputeStatistics(2)}")
        except Exception:
            pass
    finally:
        if doc is not None:
            try:
                doc.Close(SaveChanges=-1)
            except Exception:
                pass
        try:
            word.Quit()
        except Exception:
            pass
        time.sleep(0.5)

    # ---------- 校验 ----------
    n_emb = 0
    if os.path.exists(out_path):
        with zipfile.ZipFile(out_path) as z:
            names = z.namelist()
            n_emb = len([n for n in names
                         if n.startswith("word/embeddings/") and n.lower().endswith(".vsdx")])
            n_emf = len([n for n in names
                         if n.startswith("word/media/") and n.lower().endswith(".emf")])
            n_png = len([n for n in names
                         if n.startswith("word/media/") and n.lower().endswith(".png")])
    else:
        n_emf = n_png = 0

    print("\n[embed_vsdx] 结果")
    print(f"  已替换为 VSDX OLE：{len(replaced)} 张")
    print(f"  保留 PNG：{len(kept_png)} 张")
    print(f"  跳过（非结构图）：{len(skipped)} 个")
    if kept_png:
        print("  保留 PNG 明细：")
        for fig_id, alt, why in kept_png:
            print(f"    - {fig_id} {alt}：{why}")
    if replaced:
        print("  已替换明细：")
        for fig_id, alt, name, w, h in replaced:
            print(f"    - {fig_id} <- {name}（{w}×{h} pt）")
    print(f"\n[embed_vsdx] docx 内：embeddings={n_emb}，EMF 预览={n_emf}，PNG={n_png}")
    if n_emb != len(replaced):
        print(f"  [WARN] embeddings 数量与替换数不一致（{n_emb} != {len(replaced)}），请检查 Word 保存结果")
    if n_emf < n_emb:
        print("  [WARN] EMF 预览少于 embeddings 数量，非 Visio 环境可能显示不全")

    if make_pdf:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import update_fields
        update_fields.update_docx(out_path, make_pdf)

    return len(replaced), len(kept_png)


def main():
    ap = argparse.ArgumentParser(description="把论文中的结构图原位替换为 VSDX OLE（可编辑版）")
    ap.add_argument("docx", help="build_docx.py 生成的 PNG 版 docx")
    ap.add_argument("--figs", default="figs", help="vsdx/png 所在目录")
    ap.add_argument("--out", default="output/论文_可编辑版.docx")
    ap.add_argument("--pdf", default=None, help="同时更新域并导出 PDF")
    ap.add_argument("--all", action="store_true",
                    help="替换所有能找到 vsdx 的图（默认只替换第3–4章结构图，第5章截图保留 PNG）")
    args = ap.parse_args()
    replaced, kept = embed(args.docx, args.figs, args.out, args.pdf,
                           structure_only=not args.all)
    print(f"\n[embed_vsdx] 完成：{args.out}")
    if kept:
        print(f"[embed_vsdx] 注意：有 {kept} 张图保留 PNG（见上方明细），可编辑版仍可正常显示。")


if __name__ == "__main__":
    main()
