#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_manuscript.py —— 论文稿内容闸门（在 build_docx 之前运行）

检查：
  1. 硬性章节框架（1–6 章、结论、参考文献、致谢、附录；第 3/4/6 章必备小节）
  2. 各章字数与全文篇幅（正文硬性区间 12000–16000 字，超出或不足均阻断）
  3. 图/表编号连续性、题注与正文引用闭合、图在正文中被引导
  4. 第五章每个小节是否有界面截图或截图占位
  5. 参考文献 [n] 与文末条目闭合、数量
  6. 未完成/过程性措辞、重复标点、匿名引用、模板过渡词、超长句等降 AIGC 机械指标
  7. 摘要/关键词/英文摘要完整性
  8. 字段表“注释”列是否 ≤4 个汉字

用法：
  python check_manuscript.py manuscript.md
  python check_manuscript.py manuscript.md --draft          # 分章写作阶段：总字数未达标只警告
  python check_manuscript.py manuscript.md --json report.json --out report.md
退出码：0=通过（可能有警告），1=存在阻断问题。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict

CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
CITATION_RE = re.compile(r"\[\d+(?:[-–]\d+)?\]")
FIG_REF_RE = re.compile(r"图\s*(\d+)\s*[\.．]\s*(\d+)")
TAB_REF_RE = re.compile(r"表\s*(\d+)\s*[\.．]\s*(\d+)")
FIG_CAP_RE = re.compile(r"^图\s*(\d+)\s*[\.．]\s*(\d+)\s*(.*)$")
TAB_CAP_RE = re.compile(r"^表\s*(\d+)\s*[\.．]\s*(\d+)\s*(.*)$")

PLACEHOLDER_WORDS = ["待补充", "待完善", "待作者补充", "TBD", "初稿", "占位文字",
                     "后续补充", "后续完善", "待补"]
PROCESS_WORDS = ["根据源码", "从源码", "源码文件", "从代码看", "根据代码", "查看源码",
                 "本地路径", "当前材料", "证据显示", "代码证据"]

TEMPLATE_TRANSITIONS = ["首先", "其次", "再次", "最后", "综上所述", "总而言之",
                        "值得注意的是", "不难发现", "众所周知", "由此可见"]
ANON_CITATIONS = ["有研究指出", "研究表明", "相关研究表明", "据报道", "有学者认为",
                  "有研究认为", "业内普遍认为"]

REQUIRED_TOP = ["摘要", "ABSTRACT", "目录", "第1章", "第2章", "第3章",
                "第4章", "第5章", "第6章", "结论", "参考文献", "致谢"]
REQUIRED_SUBS = {
    "第1章": ["1.1", "1.2", "1.3"],
    "第3章": ["3.1", "3.1.1", "3.1.2", "3.1.3", "3.2", "3.2.1", "3.2.2", "3.2.3"],
    "第4章": ["4.1", "4.2", "4.3", "4.3.1", "4.3.2", "4.3.3"],
    "第6章": ["6.1", "6.2", "6.3", "6.4"],
}
MIN_SUBS = {"第2章": 3, "第5章": 2}

# 各章预算之和 = 12000–16000，与全文硬性区间一致
WORD_BUDGET = {
    "第1章": (1200, 1800), "第2章": (1000, 1500), "第3章": (2000, 2500),
    "第4章": (2800, 3500), "第5章": (3000, 3900), "第6章": (1400, 1900),
    "结论": (600, 900),
}
TOTAL_MIN, TOTAL_MAX = 12000, 16000   # 红线：正文总字数必须落在此闭区间


def cn_len(text):
    return len(CN_CHAR_RE.findall(text))


def word_count(text):
    """按 Word“字数”口径估算：中文字符 + 西文单词 + 数字串。"""
    return cn_len(text) + len(LATIN_WORD_RE.findall(text)) + len(NUMBER_RE.findall(text))


def norm(t):
    return t.replace("\u3000", "").replace(" ", "").replace("\t", "")


def split_sentences(text):
    parts = re.split(r"[。！？!?；;]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 4]


class Block:
    __slots__ = ("kind", "text", "extra", "line", "chapter", "section", "subsection")

    def __init__(self, kind, text="", extra=None, line=0):
        self.kind = kind
        self.text = text
        self.extra = extra
        self.line = line
        self.chapter = ""
        self.section = ""
        self.subsection = ""


def parse(lines):
    blocks = []
    chapter = section = subsection = ""
    in_front = bool(lines and lines[0].strip() == "---")
    fm_end = -1
    if in_front:
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
    i = fm_end + 1 if fm_end > 0 else 0
    in_comment = False
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            i += 1
            continue
        if not line:
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1:
                chapter, section, subsection = text, "", ""
            elif level == 2:
                section, subsection = text, ""
            else:
                subsection = text
            b = Block("h", text, level, i + 1)
            blocks.append(b)
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            start = i + 1
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            b = Block("table", "", {"header": header, "rows": rows, "start": start}, i)
            blocks.append(b)
            continue
        mi = IMG_RE.match(line)
        if mi:
            blocks.append(Block("img", mi.group(1), mi.group(2), i + 1))
            i += 1
            continue
        if line in ("<!--TOC-->", "<!-- toc -->", "<!--PAGEBREAK-->", "<!-- pagebreak -->"):
            i += 1
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            i += 1          # 注释/写作提示不参与检查
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append(Block("li", line[2:].strip(), None, i + 1))
        else:
            blocks.append(Block("p", line, None, i + 1))
        i += 1
    # 回填章节上下文
    ch = sec = sub = ""
    for b in blocks:
        if b.kind == "h":
            if b.extra == 1:
                ch, sec, sub = b.text, "", ""
            elif b.extra == 2:
                sec, sub = b.text, ""
            else:
                sub = b.text
        b.chapter, b.section, b.subsection = ch, sec, sub
    return blocks


def chapter_of(heading):
    """把标题归一成 第X章 / 结论 / 参考文献 …"""
    n = norm(heading)
    m = re.match(r"^(第\d+章)", n)
    if m:
        return m.group(1)
    for key in ("结论", "参考文献", "致谢", "附录", "摘要", "ABSTRACT", "目录"):
        if n.upper().startswith(key.upper()):
            return key
    return n


def section_number(text):
    m = re.match(r"^(\d+(?:\.\d+){0,2})", norm(text))
    return m.group(1) if m else ""


def check(path, draft=False):
    base_dir = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks = parse(lines)
    errors, warnings, info = [], [], []

    # ---------- 1. 结构 ----------
    top = []
    for b in blocks:
        if b.kind == "h" and b.extra == 1:
            top.append(chapter_of(b.text))
    for req in REQUIRED_TOP:
        if req not in top:
            errors.append(f"缺少一级标题：{req}")
    if top:
        order = [t for t in top if t in REQUIRED_TOP]
        expected = [t for t in REQUIRED_TOP if t in order]
        if order != expected:
            errors.append(f"一级标题顺序不符合规范：实际 {order}")

    # 小节
    for chap, subs in REQUIRED_SUBS.items():
        present = set()
        for b in blocks:
            if b.kind == "h" and b.extra in (2, 3) and chapter_of(b.chapter) == chap:
                present.add(section_number(b.text))
        missing = [s for s in subs if s not in present]
        if missing:
            errors.append(f"{chap} 缺少必备小节：{', '.join(missing)}")
    for chap, minimum in MIN_SUBS.items():
        count = sum(1 for b in blocks if b.kind == "h" and b.extra == 2 and chapter_of(b.chapter) == chap)
        if count < minimum:
            warnings.append(f"{chap} 二级小节只有 {count} 个，建议至少 {minimum} 个")

    # 附录内容
    appendix_idx = next((i for i, b in enumerate(blocks) if chapter_of(b.chapter) == "附录"
                         and b.kind == "h" and b.extra == 1), None)
    if appendix_idx is not None:
        rest = [b for b in blocks[appendix_idx + 1:] if b.kind in ("p", "li", "table", "img")]
        if not rest:
            warnings.append("附录只有标题没有内容（空附录比没有更严重，建议删掉或补齐）")

    # ---------- 2. 字数 ----------
    ch_words = Counter()
    ch_chars = Counter()
    for b in blocks:
        ch = chapter_of(b.chapter)
        if not ch:
            continue
        if b.kind in ("p", "li"):
            ch_words[ch] += word_count(b.text)
            ch_chars[ch] += cn_len(b.text)
        elif b.kind == "table":
            # Word 字数包含表格文字；正文表格一并计入
            cells = [b.extra.get("header", [])] + b.extra.get("rows", [])
            for row in cells:
                for cell in row:
                    ch_words[ch] += word_count(cell)
                    ch_chars[ch] += cn_len(cell)
        elif b.kind == "img":
            # 图题注也是正文的一部分
            ch_words[ch] += word_count(b.text)
            ch_chars[ch] += cn_len(b.text)
    total = sum(ch_words.get(f"第{i}章", 0) for i in range(1, 7)) + ch_words.get("结论", 0)
    total_cn = sum(ch_chars.get(f"第{i}章", 0) for i in range(1, 7)) + ch_chars.get("结论", 0)
    for chap, (lo, hi) in WORD_BUDGET.items():
        n = ch_words.get(chap, 0)
        if n < lo:
            warnings.append(f"{chap} 正文约 {n} 字，低于建议下限 {lo} 字")
        elif n > hi:
            warnings.append(f"{chap} 正文约 {n} 字，高于建议上限 {hi} 字（注意篇幅均衡）")
    in_range = TOTAL_MIN <= total <= TOTAL_MAX
    total_msg = (f"正文总字数（第1章–结论）：{total} 字"
                 f"（其中中文字符 {total_cn}），硬性区间 {TOTAL_MIN}–{TOTAL_MAX} 字")
    if not in_range:
        if draft:
            warnings.append(total_msg + "；当前为草稿模式，成稿前必须落回区间")
        else:
            direction = "低于下限" if total < TOTAL_MIN else "超过上限"
            errors.append(total_msg + f"；当前{direction}，必须调整到区间内")
    info.append(total_msg)
    # 全文口径（含摘要/参考文献/致谢/附录）仅供参考，硬红线只约束正文
    doc_words = 0
    for b in blocks:
        if b.kind in ("p", "li"):
            doc_words += word_count(b.text)
        elif b.kind == "table":
            for row in [b.extra.get("header", [])] + b.extra.get("rows", []):
                for cell in row:
                    doc_words += word_count(cell)
        elif b.kind == "img":
            doc_words += word_count(b.text)
    info.append(f"全文（含摘要/参考文献/致谢/附录）约 {doc_words} 字，供参考；硬红线只约束正文")

    # ---------- 3. 图 ----------
    fig_caps = []
    for b in blocks:
        if b.kind == "img":
            m = FIG_CAP_RE.match(b.text.strip())
            if m:
                fig_caps.append((int(m.group(1)), int(m.group(2)), b.text.strip(), b))
            else:
                warnings.append(f"图片题注不以“图X.Y”开头（第 {b.line} 行）：{b.text}")
            src = str(b.extra or "").strip()
            if src and not src.startswith("PENDING"):
                p = src if os.path.isabs(src) else os.path.join(base_dir, src)
                if not os.path.exists(p):
                    errors.append(f"图片文件不存在：{src}（第 {b.line} 行）")
    fig_refs = []
    for b in blocks:
        if b.kind in ("p", "li", "h"):
            for m in FIG_REF_RE.finditer(b.text):
                fig_refs.append((int(m.group(1)), int(m.group(2)), b))
    ref_lines = {}
    for c, n, b in fig_refs:
        ref_lines.setdefault((c, n), []).append(b.line)
    cap_set = {(c, n) for c, n, _, _ in fig_caps}
    for c, n, text, b in fig_caps:
        if not any(line < b.line for line in ref_lines.get((c, n), [])):
            errors.append(f"图 {c}.{n}「{text}」出现前没有“如图 {c}.{n} 所示”的引导句")
    for c, n, b in fig_refs:
        if (c, n) not in cap_set:
            errors.append(f"正文引用了不存在的图 {c}.{n}（第 {b.line} 行）")
    # 编号连续
    by_ch = OrderedDict()
    for c, n, _, _ in fig_caps:
        by_ch.setdefault(c, []).append(n)
    for c, nums in by_ch.items():
        if nums != list(range(1, len(nums) + 1)):
            errors.append(f"第 {c} 章图编号不连续：{nums}")
    require_figs = {(3, 1), (3, 2), (4, 1), (4, 2), (4, 3), (4, 4),
                    (4, 5), (4, 6), (4, 7), (4, 8)}
    missing_figs = sorted(require_figs - cap_set)
    if missing_figs:
        warnings.append("缺少硬性大纲要求的图：" + "、".join(f"图{c}.{n}" for c, n in missing_figs))

    # 第五章截图：优先按三级功能小节逐个检查
    ch5_all = [(i, b) for i, b in enumerate(blocks)
               if b.kind == "h" and b.extra in (2, 3) and chapter_of(b.chapter) == "第5章"]
    ch5_targets = [(i, b) for i, b in ch5_all if b.extra == 3] or \
                  [(i, b) for i, b in ch5_all if b.extra == 2]
    for idx, (bi, sec_b) in enumerate(ch5_targets):
        end_line = ch5_targets[idx + 1][1].line if idx + 1 < len(ch5_targets) else 10 ** 9
        has_img = any(b.kind == "img" and sec_b.line < b.line < end_line for b in blocks)
        if not has_img:
            warnings.append(f"第5章「{sec_b.text}」没有界面截图或截图占位")
    pending = [b for b in blocks if b.kind == "img" and "PENDING" in str(b.extra)]
    if pending:
        warnings.append(f"有 {len(pending)} 处截图占位待替换（第五章提交前必须换成真实截图）")

    # ---------- 4. 表 ----------
    tab_caps = []
    for i, b in enumerate(blocks):
        if b.kind == "p":
            m = TAB_CAP_RE.match(b.text.strip())
            if m:
                tab_caps.append((int(m.group(1)), int(m.group(2)), b.text.strip(), b, i))
    tab_ref_lines = {}
    for b in blocks:
        if b.kind in ("p", "li", "h"):
            for m in TAB_REF_RE.finditer(b.text):
                key = (int(m.group(1)), int(m.group(2)))
                tab_ref_lines.setdefault(key, []).append(b.line)
    for c, n, text, b, i in tab_caps:
        # 题注后应紧跟表格块
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt is None or nxt.kind != "table":
            warnings.append(f"表 {c}.{n} 题注后没有紧邻表格（第 {b.line} 行）")
        if not any(line < b.line for line in tab_ref_lines.get((c, n), [])):
            errors.append(f"表 {c}.{n}「{text}」出现前没有“如表 {c}.{n} 所示”的引导句")
    tab_cap_set = {(c, n) for c, n, _, _, _ in tab_caps}
    for c, n in tab_ref_lines:
        if (c, n) not in tab_cap_set:
            errors.append(f"正文引用了不存在的表 {c}.{n}")
    by_ch = OrderedDict()
    for c, n, _, _, _ in tab_caps:
        by_ch.setdefault(c, []).append(n)
    for c, nums in by_ch.items():
        if nums != list(range(1, len(nums) + 1)):
            errors.append(f"第 {c} 章表编号不连续：{nums}")

    # 字段表“注释”列 ≤4 汉字
    for b in blocks:
        if b.kind != "table":
            continue
        header = b.extra["header"]
        if "注释" not in header:
            continue
        ci = header.index("注释")
        for row in b.extra["rows"]:
            if ci < len(row):
                cell = row[ci].strip()
                n_cn = cn_len(cell)
                if n_cn > 4:
                    errors.append(f"字段表注释超过 4 个汉字（第 {b.extra['start']} 行附近）：{cell}")

    # ---------- 5. 参考文献 ----------
    ref_entries = set()
    in_refs = False
    ref_count = 0
    for b in blocks:
        if b.kind == "h" and b.extra == 1:
            in_refs = chapter_of(b.text) == "参考文献"
            continue
        if in_refs and b.kind == "p":
            m = re.match(r"^\[(\d+)\]", b.text)
            if m:
                ref_entries.add(int(m.group(1)))
                ref_count += 1
    cited = set()
    for b in blocks:
        if b.kind in ("p", "li"):
            for m in CITATION_RE.finditer(b.text):
                body = m.group(0).strip("[]")
                if "-" in body or "–" in body:
                    try:
                        a, z = re.split(r"[-–]", body)
                        cited.update(range(int(a), int(z) + 1))
                    except Exception:
                        pass
                else:
                    cited.add(int(body))
    missing_refs = sorted(cited - ref_entries)
    uncited = sorted(ref_entries - cited)
    if missing_refs:
        errors.append(f"正文引用了文末不存在的文献编号：{missing_refs}")
    if uncited:
        warnings.append(f"文末有正文未引用的文献编号：{uncited}")
    if ref_count < 10:
        warnings.append(f"参考文献仅 {ref_count} 条，本科论文一般不少于 10–15 条")

    # ---------- 6. 摘要与关键词 ----------
    def section_text(title):
        start = None
        for i, b in enumerate(blocks):
            if b.kind == "h" and b.extra == 1 and chapter_of(b.text) == title:
                start = i
                break
        if start is None:
            return ""
        out = []
        for b in blocks[start + 1:]:
            if b.kind == "h" and b.extra == 1:
                break
            if b.kind == "p":
                out.append(b.text)
        return "\n".join(out)

    cn_abs = section_text("摘要")
    en_abs = section_text("ABSTRACT")
    if cn_abs and "关键词" not in cn_abs:
        warnings.append("中文摘要后未找到“关键词：”")
    if en_abs and "key words" not in en_abs.lower():
        warnings.append("英文摘要后未找到“Key words”")
    if cn_abs and en_abs:
        cn_n = cn_len(cn_abs)
        en_n = len(re.findall(r"[A-Za-z]+", en_abs))
        if cn_n > 0 and en_n < cn_n * 0.20:
            warnings.append(f"英文摘要可能明显缩水（中文 {cn_n} 字，英文 {en_n} 词）")

    # ---------- 7. 文本质量与降 AIGC 机械指标 ----------
    body_blocks = [b for b in blocks if b.kind in ("p", "li")
                   and chapter_of(b.chapter) not in ("摘要", "ABSTRACT", "目录", "参考文献", "致谢", "附录")]
    all_body_text = "\n".join(b.text for b in body_blocks)
    for w in PLACEHOLDER_WORDS:
        hits = [b for b in body_blocks if w in b.text]
        if hits:
            errors.append(f"正文存在未完成措辞“{w}”×{len(hits)}（第 {hits[0].line} 行起）")
    for w in PROCESS_WORDS:
        hits = [b for b in body_blocks if w in b.text]
        if hits:
            errors.append(f"正文存在过程/证据措辞“{w}”×{len(hits)}（第 {hits[0].line} 行起）")

    # 超长句
    long_sents = []
    for b in body_blocks:
        for s in split_sentences(b.text):
            if cn_len(s) > 40:
                long_sents.append((b.line, s))
    if long_sents:
        warnings.append(f"存在 {len(long_sents)} 个超过 40 字的句子（示例：第 {long_sents[0][0]} 行“{long_sents[0][1][:30]}…”）")

    # 连续三句长度相近
    rhythm = []
    for b in body_blocks:
        sents = split_sentences(b.text)
        for i in range(len(sents) - 2):
            lens = [len(s) for s in sents[i:i + 3]]
            if all(lens[i + 1] >= lens[i] * 0.7 for i in range(2)) and \
               all(lens[i + 1] <= lens[i] * 1.3 for i in range(2)):
                rhythm.append((b.line, lens))
                break
    if rhythm:
        warnings.append(f"有 {len(rhythm)} 段出现连续 3 句长度相近（句长节奏偏平，示例第 {rhythm[0][0]} 行）")

    # 模板过渡词
    counts = {w: all_body_text.count(w) for w in TEMPLATE_TRANSITIONS}
    used = {w: c for w, c in counts.items() if c}
    if sum(used.values()) > max(3, len(all_body_text) // 1000):
        warnings.append("模板过渡词偏多：" + "、".join(f"{w}×{c}" for w, c in used.items()))
    for w in ("首先", "其次", "最后"):
        if all_body_text.count(w) >= 3:
            warnings.append(f"“{w}”出现 {all_body_text.count(w)} 次，注意避免“首先—其次—最后”模板链")

    # 空壳句头
    shell = [b for b in body_blocks if re.match(r"^(随着|众所周知|在.{0,12}背景下)", b.text)
             and ("随着" in b.text[:6] or "众所周知" in b.text[:6])]
    if shell:
        warnings.append(f"有 {len(shell)} 段以“随着/众所周知/在…背景下”空壳句开头（第 {shell[0].line} 行）")

    # 匿名引用
    anon = [b for b in body_blocks if any(w in b.text for w in ANON_CITATIONS)]
    if anon:
        warnings.append(f"存在匿名引用（有研究指出/研究表明等）×{len(anon)}，应改为具名引用或标出处（第 {anon[0].line} 行）")

    # 重复标点/叠词
    bad_punct = re.findall(r"[。，、；：]{2,}", all_body_text)
    if bad_punct:
        errors.append(f"存在重复标点 {len(bad_punct)} 处（如“{bad_punct[0]}”）")
    dup_words = re.findall(r"([\u4e00-\u9fff]{2,4})\1", all_body_text)
    if dup_words:
        warnings.append(f"存在疑似重复词 {len(dup_words)} 处（如“{dup_words[0]}”）")

    # 术语混用
    term_groups = [("沙箱", "沙盘", "沙盒"), ("登录", "登陆"), ("账号", "帐号"),
                   ("服务端", "服务器"), ("Spring Boot", "SpringBoot"),
                   ("MyBatis-Plus", "MybatisPlus"), ("微信小程序", "小程序")]
    for group in term_groups:
        present = [g for g in group if g in all_body_text]
        # 去掉被更长术语包含的短词（如“小程序”包含于“微信小程序”）
        present = [g for g in present if not any(g != other and g in other for other in present)]
        if len(present) > 1:
            warnings.append("术语可能混用：" + " / ".join(present))

    # ---------- 8. 实体属性图覆盖 ----------
    entity_cfg = os.path.join(base_dir, "specs", "entity-attributes.json")
    attr_caps = [c for c in fig_caps if "实体属性图" in c[2] or "实体-属性图" in c[2]]
    if os.path.exists(entity_cfg):
        try:
            with open(entity_cfg, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            names = [str(e.get("name", "")).strip() for e in cfg.get("entities", [])
                     if str(e.get("name", "")).strip()]
            for name in names:
                if not any((f"{name}实体属性图" in c[2] or f"{name}实体-属性图" in c[2])
                           for c in attr_caps):
                    errors.append(f"缺少实体属性图：{name}（E-R 图中的每个实体都要有一张）")
            if len(attr_caps) < len(names):
                errors.append(f"实体属性图只有 {len(attr_caps)} 张，配置要求 {len(names)} 张")
            unmatched = [c[2] for c in attr_caps
                         if not any((f"{name}实体属性图" in c[2] or f"{name}实体-属性图" in c[2])
                                    for name in names)]
            if unmatched:
                warnings.append("以下实体属性图题注在配置中找不到对应实体（配置改了但稿件没同步）："
                                + "；".join(unmatched[:5]))
            info.append(f"实体属性图：{len(attr_caps)} 张 / 配置实体 {len(names)} 个")
        except Exception as ex:
            warnings.append(f"读取 specs/entity-attributes.json 失败：{ex}")
    elif not attr_caps:
        warnings.append("未找到 specs/entity-attributes.json，且正文没有实体属性图；"
                        "E-R 图中的每个实体都应有一张实体-属性图")

    # ---------- 9. 输出 ----------
    info.append(f"图表数量：图 {len(fig_caps)} 张，表 {len(tab_caps)} 张")
    info.append(f"参考文献：{ref_count} 条；正文被引编号：{len(cited)} 个")
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "stats": {
            "body_words": total,
            "body_chars": total_cn,
            "document_words": doc_words,
            "word_range": [TOTAL_MIN, TOTAL_MAX],
            "word_range_ok": in_range,
            "chapters": dict(ch_words),
            "figures": len(fig_caps),
            "tables": len(tab_caps),
            "references": ref_count,
            "pending_screenshots": len(pending),
        },
    }
    return result


def print_report(result):
    print("=" * 68)
    print("论文稿内容闸门")
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
    ap.add_argument("manuscript")
    ap.add_argument("--json", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true", help="警告也视为失败")
    ap.add_argument("--draft", action="store_true",
                    help="分章写作阶段：总字数未落在 12000–16000 时只警告；成稿检查不要加此参数")
    args = ap.parse_args()

    result = check(args.manuscript, draft=args.draft)
    print_report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("# 论文稿内容闸门报告\n\n")
            for s in result["info"]:
                f.write(f"- {s}\n")
            if result["errors"]:
                f.write("\n## 阻断问题\n\n")
                for e in result["errors"]:
                    f.write(f"- {e}\n")
            if result["warnings"]:
                f.write("\n## 警告\n\n")
                for w in result["warnings"]:
                    f.write(f"- {w}\n")
            f.write("\n## 结论\n\n")
            f.write("通过（有警告）\n" if result["ok"] else "未通过\n")
    ok = result["ok"] and (not args.strict or not result["warnings"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
