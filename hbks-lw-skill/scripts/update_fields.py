#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_fields.py —— 用本机 Word 更新目录域、页码域，并可选导出 PDF

用法：
  python update_fields.py 论文.docx
  python update_fields.py 论文.docx --pdf 论文.pdf
  python update_fields.py 论文.docx --pdf 论文.pdf --pages 1-12

说明：
  - 目录必须是自动目录域（build_docx.py 已生成 TOC 域），本脚本会更新整个目录。
  - 页眉/页脚中的 PAGE 域也会逐节更新，避免出现缓存的旧页码。
  - 导出 PDF 后请按 02-writing-standards.md §10 做版面检查。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from office_prepare import prepare_office
from word_layout import inspect_document, write_report


def update_docx(path, pdf=None, pages=None):
    import win32com.client
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    # Word 启动与重排会读默认打印机来算版面；临时切到本地虚拟打印机，
    # 避免每次自动化都去探测网络打印机（退出时自动恢复原设置）。
    with prepare_office():
        _update_with_word(win32com.client, path, pdf, pages)


def _update_with_word(win32com, path, pdf, pages):
    word = win32com.DispatchEx("Word.Application")
    word.Visible = False
    try:
        word.DisplayAlerts = 0
    except Exception:
        pass
    doc = None
    try:
        doc = word.Documents.Open(path, ReadOnly=False, AddToRecentFiles=False)
        # 正文域
        doc.Fields.Update()
        # 各节页眉页脚域
        for i in range(1, doc.Sections.Count + 1):
            sec = doc.Sections(i)
            for story in (sec.Headers, sec.Footers):
                for j in range(1, story.Count + 1):
                    try:
                        story(j).Range.Fields.Update()
                    except Exception:
                        pass
        # 目录
        for i in range(1, doc.TablesOfContents.Count + 1):
            try:
                doc.TablesOfContents(i).Update()
            except Exception as e:
                print(f"[update_fields] 目录更新失败：{e}")
        doc.Repaginate()
        # 分页变化后再刷新目录页码，避免使用拆表前缓存。
        for i in range(1, doc.TablesOfContents.Count + 1):
            doc.TablesOfContents(i).UpdatePageNumbers()
        doc.Repaginate()
        report = inspect_document(doc)
        doc.Save()
        write_report(report, path)
        if not report['ok']:
            raise RuntimeError('版面闸门失败，未导出提交 PDF：' + '；'.join(report['errors']) +
                               '。请运行 paginate_tables.py 后再更新域。')
        print(f"[update_fields] 已更新目录与页码域：{path}")
        try:
            print(f"[update_fields] 总页数：{doc.ComputeStatistics(2)}")
            print(f"[update_fields] Word 全文统计：{doc.ComputeStatistics(0)} 字 / "
                  f"{doc.ComputeStatistics(3)} 字符（不含空格）")
            print("[update_fields] 注意：硬性 12000–16000 约束正文（第1章–结论），"
                  "以 check_manuscript.py 的 body_words 为准；此处全文统计供交叉核对。")
        except Exception:
            pass
        if pdf:
            pdf = os.path.abspath(pdf)
            os.makedirs(os.path.dirname(pdf) or ".", exist_ok=True)
            if os.path.exists(pdf):
                os.remove(pdf)
            kwargs = dict(OutputFileName=pdf, ExportFormat=17, OpenAfterExport=False,
                          OptimizeFor=0, Range=0, Item=0, IncludeDocProps=True,
                          CreateBookmarks=1, DocStructureTags=True,
                          BitmapMissingFonts=True, UseISO19005_1=False)
            if pages:
                kwargs["Range"] = 4          # wdExportFromTo
                start, end = pages.split("-", 1)
                kwargs["From"] = int(start)
                kwargs["To"] = int(end)
            try:
                doc.ExportAsFixedFormat(**kwargs)
            except Exception:
                doc.ExportAsFixedFormat(pdf, 17)
            print(f"[update_fields] 已导出 PDF：{pdf}")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--pages", default=None, help="仅导出指定页范围，如 1-12")
    args = ap.parse_args()
    update_docx(args.docx, args.pdf, args.pages)


if __name__ == "__main__":
    main()
