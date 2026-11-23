#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_materials.py — 从「开题材料」里抽取作者信息与证据文本

支持两种学校模板：
  A 河北科技师范学院：题目是裸段落，字段形如「学 生 姓 名：张三」
  B 河北工程技术学院：题目在「毕业设计题目:」后，字段形如「姓名: 张三   学 号:」

设计原则：**只报高置信度的值**。抽不到就是 null，绝不猜、绝不编。
缺的字段进 missing_required，由流水线决定是"问人"还是"拒绝上传"。

用法：
    python parse_materials.py <开题材料目录> [--out student.json] [--dump-text 文本.md]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import docx

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# 字段标签（按长度降序匹配，避免「姓名」抢先吃掉「学生姓名」）
FIELD_LABELS = [
    ("院系名称", "学院"),
    ("专业名称", "专业"),
    ("学生姓名", "姓名"),
    ("学生学号", "学号"),
    ("指导教师", "指导教师"),
    ("专业班级", "专业"),
    ("学院", "学院"),
    ("姓名", "姓名"),
    ("学号", "学号"),
]

LABEL_ALTERNATION = "|".join(
    r"\s*".join(re.escape(ch) for ch in label)
    for label, _ in sorted(FIELD_LABELS, key=lambda x: -len(x[0]))
)

# 「学院:」这种后面紧接另一个标签的情况，值留空
LABEL_RE = re.compile(rf"({LABEL_ALTERNATION})\s*[:：]")

# 校名识别：优先认「抬头行」——整行只有校名，这是最可靠的信号。
# 不能全篇乱搜，否则「数学与信息科技学院」这种院系名会被误当成学校。
SCHOOL_LINE_RE = re.compile(r"^\s*([\u4e00-\u9fa5]{2,16}(?:大学|学院))\s*$")
SCHOOL_ANY_RE = re.compile(r"([\u4e00-\u9fa5]{2,16}(?:大学|学院))")
# 出现这些词的句子不是抬头，是院系/专业栏
SCHOOL_FALSE_POSITIVE = ("院（系", "院(系", "系、部", "专业", "班级", "系部")

TITLE_PATTERNS = [
    re.compile(r"(?:毕业设计|毕业论文)\s*题目\s*[:：]\s*(.+)$"),
    re.compile(r"题\s*目\s*[:：]\s*(.+)$"),
]

HEADING_HINTS = ("本科毕业论文（设计）", "本科毕业论文(设计)", "本科生毕业设计")

# 这些行不是字段行，跳过
SKIP_VALUE_PREFIX = ("签名", "意见", "审查", "月", "日")


# --------------------------------------------------------------------------
# 文本抽取
# --------------------------------------------------------------------------

def docx_lines(path: Path) -> list[str]:
    """按文档顺序取出段落 + 表格文字。"""
    d = docx.Document(str(path))
    lines: list[str] = []
    for p in d.paragraphs:
        t = p.text.strip()
        if t:
            lines.append(t)
    for tbl in d.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for ln in cell.text.splitlines():
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
    return lines


def pptx_lines(path: Path) -> list[str]:
    try:
        from pptx import Presentation
    except ImportError:
        return []
    out: list[str] = []
    try:
        prs = Presentation(str(path))
    except Exception:
        return []
    for idx, slide in enumerate(prs.slides, 1):
        out.append(f"--- 第{idx}页 ---")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(r.text for r in para.runs).strip()
                    if t:
                        out.append(t)
    return out


# --------------------------------------------------------------------------
# 字段解析
# --------------------------------------------------------------------------

def _squash(line: str) -> str:
    """压掉空白、抹平「院（系、部）名称」这类写法差异。"""
    s = re.sub(r"[\s\u3000]", "", line)
    s = re.sub(r"[（(][^）)]{0,6}[）)]", "", s)   # 去掉括号内的 系、部 等
    return s


def extract_labeled_fields(lines: list[str]) -> dict[str, str]:
    """在一批行里按标签抽值。空值不返回（留给缺失检查）。"""
    found: dict[str, str] = {}
    canon = dict(FIELD_LABELS)

    for raw in lines:
        squashed = _squash(raw)
        matches = list(LABEL_RE.finditer(squashed))
        if not matches:
            continue
        for i, m in enumerate(matches):
            label = re.sub(r"\s+", "", m.group(1))
            key = canon.get(label)
            if not key:
                continue
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(squashed)
            value = squashed[start:end].strip(" :：")
            if not value:
                continue
            if value.startswith(SKIP_VALUE_PREFIX):
                continue
            # 值里不该再夹标签；长度离谱的多半是正文
            if len(value) > 30:
                continue
            found.setdefault(key, value)
    return found


def extract_title(lines: list[str], template: str) -> str | None:
    # 1) 显式「题目:」
    for raw in lines[:20]:
        for pat in TITLE_PATTERNS:
            m = pat.search(_squash(raw))
            if m:
                t = m.group(1).strip(" :：")
                if len(t) >= 6:
                    return t

    # 2) 模板 A：标题行之后的第一条裸段落
    if template == "A":
        heading_idx = None
        for i, raw in enumerate(lines[:10]):
            if any(h in raw for h in HEADING_HINTS):
                heading_idx = i
                break
        if heading_idx is not None:
            for raw in lines[heading_idx + 1: heading_idx + 5]:
                s = raw.strip()
                if LABEL_RE.search(_squash(s)):
                    continue
                if len(s) >= 8 and not s.endswith("制") and "教务处" not in s:
                    return s
    return None


def extract_school(lines: list[str]) -> str | None:
    # 1) 抬头行：前 6 行里整行就是「XX大学/XX学院」
    for raw in lines[:6]:
        m = SCHOOL_LINE_RE.match(raw)
        if m:
            return m.group(1)

    # 2) 退一步：前 6 行里包含校名，但排除院系/专业栏那种句子
    for raw in lines[:6]:
        if any(bad in raw for bad in SCHOOL_FALSE_POSITIVE):
            continue
        m = SCHOOL_ANY_RE.search(raw)
        if m:
            return m.group(1)
    return None


# 参考文献之后紧跟的签章区，遇到就停，否则会把签名/表格吞进最后一条
REF_STOP_RE = re.compile(
    r"签名|年\s*月\s*日|带头人|院长|教学部|审查|意见|日期[:：]"
)

# GB/T 7714 文献类型标识：[J]期刊 [D]学位 [C]会议 [M]专著 [N]报纸 [R]报告 [P]专利 [S]标准 …
_REF_TYPE_RE = re.compile(r"[\[［]\s*(J|D|C|M|N|R|P|S|Z|A|G|EB|DB|CP|DS)\s*(/OL)?\s*[\]］]", re.I)


def _looks_like_ref(s: str) -> bool:
    """判断一行是不是一条参考文献。
    任务书里的必读参考文献常常**没有编号**，所以不能只认 [1] 开头。"""
    if len(s) < 12:
        return False
    if re.match(r"^[\[［(（]?\d+[\]］)）.、]\s*\S", s):   # [1] / (1) / 1.
        return True
    if _REF_TYPE_RE.search(s):                          # 有 [J]/[D]/[C] 等类型标识
        return True
    # 兜底：作者. 题名. 刊名, 2023(2): 43-57. 这种
    if re.search(r"\d{4}", s) and s.count(".") >= 2 and len(s) >= 30:
        return True
    return False


def extract_references(lines: list[str]) -> list[str]:
    """抽出「必读参考文献」里的条目（兼容编号与不编号两种版式）。"""
    refs: list[str] = []
    started = False
    for raw in lines:
        s = raw.strip()
        if not started:
            if "参考文献" in s and len(s) < 20:
                started = True
            continue

        if REF_STOP_RE.search(s):
            break

        if _looks_like_ref(s):
            refs.append(s)
            continue

        # 续行：只接受短句，长行多半是正文或表格转储，直接结束
        if refs and len(s) <= 100 and len(refs[-1]) < 300:
            refs[-1] = refs[-1] + " " + s
            continue

        break

    # 最后一条里若混入签章文字，截断
    cleaned: list[str] = []
    for r in refs:
        m = REF_STOP_RE.search(r)
        if m:
            r = r[: m.start()].rstrip(" ，,;；")
        if r:
            cleaned.append(r)
    return cleaned


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

REQUIRED = ["学号", "姓名", "专业", "题目"]


def parse(materials_dir: Path) -> dict[str, Any]:
    if not materials_dir.is_dir():
        raise SystemExit(f"目录不存在：{materials_dir}")

    docx_files = sorted(p for p in materials_dir.iterdir()
                        if p.suffix.lower() == ".docx" and not p.name.startswith("~$"))
    pptx_files = sorted(p for p in materials_dir.iterdir() if p.suffix.lower() == ".pptx")
    pdf_files = sorted(p for p in materials_dir.iterdir() if p.suffix.lower() == ".pdf")

    if not docx_files and not pptx_files:
        raise SystemExit(
            f"「{materials_dir.name}」里既没有 .docx 也没有 .pptx，无法提取任何信息。\n"
            "请先补齐任务书/开题报告再跑。"
        )

    result: dict[str, Any] = {
        "repo": materials_dir.parent.name,
        "materials_dir": str(materials_dir),
        "files": {
            "docx": [p.name for p in docx_files],
            "pptx": [p.name for p in pptx_files],
            "pdf": [p.name for p in pdf_files],
        },
        "school": None,
        "template": None,
        "fields": {},
        "missing_required": [],
        "references": [],
        "warnings": [],
    }

    # 先解析「任务书」，再解析「开题报告」补全；开题报告里字段通常更全
    ordered = sorted(docx_files, key=lambda p: (0 if "任务书" in p.name else 1, p.name))

    merged: dict[str, str] = {}
    all_lines: list[str] = []
    school = None
    template = None
    refs: list[str] = []

    for p in ordered:
        lines = docx_lines(p)
        all_lines.append(f"\n## {p.name}\n")
        all_lines.extend(lines)

        if school is None:
            school = extract_school(lines)
        if template is None:
            template = "B" if any("毕业设计题目" in _squash(l) for l in lines[:12]) else "A"

        for k, v in extract_labeled_fields(lines[:30]).items():
            merged.setdefault(k, v)

        if not refs:
            refs = extract_references(lines)

    title = extract_title([l for p in ordered for l in docx_lines(p)], template or "A")
    if title:
        merged["题目"] = title

    result["school"] = school
    result["template"] = template
    result["fields"] = {
        "学号": merged.get("学号"),
        "姓名": merged.get("姓名"),
        "专业": merged.get("专业"),
        "学院": merged.get("学院"),
        "指导教师": merged.get("指导教师"),
        "题目": merged.get("题目"),
    }
    result["missing_required"] = [k for k in REQUIRED if not result["fields"].get(k)]
    result["references"] = refs

    # 缺开题报告时明确提示（任务书够用，但证据少一截）
    if not any("开题报告" in p.name for p in docx_files):
        result["warnings"].append("没有开题报告，仅有任务书；需求/创新点证据偏少。")
    if not result["fields"].get("指导教师"):
        result["warnings"].append("指导教师为空——论文封面会留空。")

    # PPT 文字也留作证据
    ppt_text: list[str] = []
    for p in pptx_files:
        ppt_text.append(f"\n## {p.name}（开题答辩PPT）\n")
        ppt_text.extend(pptx_lines(p))

    result["_evidence_text"] = "\n".join(all_lines) + "\n".join(ppt_text)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="解析开题材料，抽取作者信息与证据文本")
    ap.add_argument("materials_dir", help="开题材料目录")
    ap.add_argument("--out", help="输出 student.json 路径")
    ap.add_argument("--dump-text", help="把抽到的全部文字另存为 Markdown")
    args = ap.parse_args(argv)

    data = parse(Path(args.materials_dir))
    evidence = data.pop("_evidence_text", "")

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)

    if args.dump_text:
        Path(args.dump_text).parent.mkdir(parents=True, exist_ok=True)
        Path(args.dump_text).write_text(evidence, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
