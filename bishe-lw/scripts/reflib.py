#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考文献库：中文来自仓库 `论文/论文推荐`，英文来自 `开题材料/外文原文`。

run.py refs harvest <代码库号>   扫描仓库材料建库，列出缺作者/缺来源的条目
run.py refs merge <代码库号>     合并补录结果（.work/refs/meta-results.json）
run.py refs verify <代码库号>    校验稿件参考文献（发布闸门）
run.py refs lib <代码库号>       查看文献库状态

设计口径：
- 中文条目只从仓库自带的推荐文献里取，不追加库外中文文献；
- 英文条目必须含开题材料的外文原文那篇，英文合计不超过 max_english（默认 3）篇；
- 脚本自身不联网：联网核对题录由 Agent 在会话里做，结果经 meta-results.json 合并；
- 题录缺作者/刊名/学校时，由 Agent 按题名精确匹配补录（见 meta-results.json），
  脚本只做合并与校验，不自己编造作者。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yx

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

EXIT_MATERIAL = 3      # 仓库里没有推荐文献目录
EXIT_GATE = 6          # 参考文献闸门未通过

DEFAULT_ZH_DIR = "论文/论文推荐"
DEFAULT_EN_GLOBS = ("开题材料/外文原文*.pdf", "开题材料/外文文献*.pdf")
DEFAULT_MIN_TOTAL = 15
DEFAULT_MAX_TOTAL = 35
DEFAULT_MAX_ENGLISH = 3

_PUNCT = re.compile(r"[\s\u3000“”‘’\"'《》「」【】（）()\[\],，.。:：;；!！?？\-—_·…、]+")
_NAME = re.compile(r"^[\u4e00-\u9fa5·]{2,6}(?:[\s，,、]+[\u4e00-\u9fa5·]{2,6}){0,11}[0-9\s*＊,，]*$")
_SUP = re.compile(r"[\s]*[\d*＊∗,]+$")


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------

def norm_title(text: str) -> str:
    """题名归一化：去标点空白、统一小写，用于题名匹配而不是展示。"""
    return _PUNCT.sub("", (text or "").lower())


def local_root(repo_query: str) -> Path:
    """按本地已拉取的目录定位代码库，不依赖云效 OpenAPI。"""
    name = (repo_query or "").strip().replace("\\", "/").split("/")[-1]
    if name.isdigit() and len(name) <= 3:
        name = f"bishe{int(name):03d}"
    cfg = yx.load_config()
    base = Path(cfg["paths"]["runs_root"]).resolve()
    root = (base / name).resolve()
    if root == base or not root.is_relative_to(base) or not root.is_dir():
        raise yx.YunxiaoError(f"本地没有 {name} 的工作目录，请先运行 init 拉取代码库")
    return root


def refs_dir(root: Path) -> Path:
    return root / ".work" / "refs"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _refs_cfg(cfg: dict) -> dict:
    return dict(cfg.get("refs") or {})


# --------------------------------------------------------------------------
# 仓库里的推荐文献（中文）
# --------------------------------------------------------------------------

def _sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur = "_head"
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            cur = line[3:].strip()
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(raw)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def parse_rec_md(path: Path) -> dict:
    """解析一篇 `论文/论文推荐/NN-题名.md`。"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    chunks = text.splitlines()
    title = ""
    for line in chunks:
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            break
    head = "\n".join(chunks[: 40])

    def grab(pattern: str) -> str:
        m = re.search(pattern, head)
        return m.group(1).strip() if m else ""

    entry = {
        "id": None,
        "origin": "rec",
        "file": path.name,
        "seq": _seq_of(path.name),
        "title": title,
        "kind": grab(r"类型[：:]\s*([^\s　]+)"),
        "year": grab(r"年份[：:]\s*(\d{4})"),
        "cited": grab(r"被引[：:]\s*(\d+)"),
        "keywords": grab(r"关键词[：:]\s*(.+)"),
        "cnki": grab(r"知网链接[：:]\s*(\S+)"),
        "category": grab(r"类别[：:]\s*(.+)"),
        "authors": [],
        "source": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "provenance": {},
    }
    pdf_rel = grab(r"原文 PDF[：:]\s*\[[^\]]*\]\(([^)]+)\)")
    if pdf_rel:
        entry["pdf_rel"] = pdf_rel

    sec = _sections(text)
    for key, val in sec.items():
        if key.startswith("具体推荐句"):
            for line in val.splitlines():
                if line.strip().startswith(">"):
                    entry["quote"] = line.strip().lstrip("> ").strip()
                    break
        elif key.startswith("建议引用位置"):
            entry["chapter"] = " ".join(val.split())
        elif key.startswith("摘要"):
            entry["abstract"] = " ".join(val.split())[:600]
    return entry


def _seq_of(filename: str) -> int | None:
    m = re.match(r"^(\d{1,3})", filename)
    return int(m.group(1)) if m else None


def _pdf_text(path: Path, pages: int = 2) -> str:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return ""
    try:
        doc = fitz.open(str(path))
        parts = [doc[i].get_text() for i in range(min(pages, doc.page_count))]
        doc.close()
        return "\n".join(parts)
    except Exception:
        return ""


def _clean_authors(names: list[str]) -> list[str]:
    out = []
    for n in names:
        n = _SUP.sub("", n.strip()).strip("，,、 ")
        if 2 <= len(n) <= 12 and re.search(r"[\u4e00-\u9fa5A-Za-z]", n):
            out.append(n)
    return out


_BAD_NAME = ("指导教师", "导师", "专业", "学科", "学院", "学位", "学号", "密级",
             "分类号", "研究方向", "论文题目", "题目", "姓名", "职称")
_AUTHOR_LABELS = ("作者姓名", "研究生姓名", "学位申请人", "作者")


def _norm_line(line: str) -> str:
    """去掉字间空格：「研 究 生 姓 名」→「研究生姓名」。"""
    return re.sub(r"\s+", "", line)


def _pick_author(val: str) -> list[str]:
    val = _SUP.sub("", (val or "").strip()).strip(":： ")
    if not (2 <= len(val) <= 6):
        return []
    if any(bad in val for bad in _BAD_NAME):
        return []
    return [val]


def authors_from_pdf(text: str, title: str, kind: str) -> dict:
    """从推荐文献 PDF 首页猜作者/学校。只填有把握的字段，猜不到就留空。"""
    got: dict[str, Any] = {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return got

    # 学位论文封面：作者姓名 / 研究生姓名 / 学位申请人，值可能写在同一行或下一行
    if kind in ("硕士", "博士"):
        for idx, line in enumerate(lines[:40]):
            norm = _norm_line(line)
            for label in _AUTHOR_LABELS:
                if not norm.startswith(label):
                    continue
                rest = norm[len(label):].lstrip("：: ")
                names = _pick_author(rest)
                if not names and idx + 1 < len(lines):
                    names = _pick_author(_norm_line(lines[idx + 1]))
                if names:
                    got["authors"] = names
                    break
            if got.get("authors"):
                break
        uni = [l for l in lines if re.match(r"^[\u4e00-\u9fa5（）()]{2,20}?大学$", l)]
        if not uni:
            uni = [l for l in lines if re.match(r"^[\u4e00-\u9fa5]{2,12}(研究院|研究所)$", l)]
        # 不拿「XX学院」当学校：封面里它多半是校内学院，写错比留空更糟
        if uni:
            got["source"] = uni[0]
        return got

    # 期刊：题名之后紧跟一行作者（题名可能折成两三行），再下面是单位
    nt = norm_title(title)
    if not nt:
        return got
    for idx, line in enumerate(lines[:25]):
        if not norm_title(line).startswith(nt[:10]):
            continue
        for cand in lines[idx + 1: idx + 5]:
            nkey = norm_title(cand)
            if not nkey or nkey in nt:                      # 题名折行的后半截，不是作者
                continue
            if "大学" in cand or "学院" in cand or "摘要" in cand or "：" in cand:
                continue
            if not _NAME.match(cand):
                continue
            if "，" not in cand and "、" not in cand and len(nkey) > 6:
                continue
            names = re.split(r"[，,、\s]+", _SUP.sub("", cand))
            got["authors"] = _clean_authors(names)
            break
        break
    return got


# --------------------------------------------------------------------------
# 外文原文（英文）
# --------------------------------------------------------------------------

_EN_SKIP = re.compile(r"https?:|homepage|contents lists|available at|keywords|abstract|"
                      r"university|college|institute|department|school of|received|accepted|"
                      r"©|journal|vol\.|press|proceedings of|©|all rights reserved", re.I)
_EN_NAME = re.compile(r"^[A-Z][A-Za-z.\-']+(?: [A-Z][A-Za-z.\-']+){1,3}$")


def _en_line_ok(line: str) -> bool:
    if "@" in line or _EN_SKIP.search(line):
        return False
    if re.fullmatch(r"[\d\s.,;:()/–-]+", line):
        return False
    return True


def parse_en_pdf(path: Path) -> dict:
    """解析外文原文首页的题名/作者/刊名/年卷页。识别不了就留空让人工确认。"""
    entry = {
        "id": "E1",
        "origin": "en_source",
        "file": path.name,
        "title": "",
        "authors": [],
        "source": "",
        "year": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": "",
        "needs_review": True,
        "provenance": {"raw": f"{path.name} 第 1 页"},
    }
    try:
        import fitz
        doc = fitz.open(str(path))
        meta = dict(doc.metadata or {})
        text = doc[0].get_text() if doc.page_count else ""
        doc.close()
    except Exception:
        return entry
    if not text.strip():
        return entry

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    js = " ".join(lines[:12])

    m = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", text)
    if m:
        entry["doi"] = m.group(1).rstrip(".,;)")

    # 1) 期刊页眉：Journal Name 2 (2023) 100050
    for line in lines[:6]:
        m = re.search(r"^(.{4,90}?)\s+(\d{1,4})\s*\((\d{4})\)\s*([A-Za-z]?\d+)?\s*$", line)
        if m and not re.search(r"https?:|available|homepage", line, re.I):
            entry["source"] = m.group(1).strip()
            entry["volume"] = m.group(2)
            entry["year"] = m.group(3)
            if m.group(4):
                entry["pages"] = m.group(4)
            break
    if not entry["year"]:
        m = re.search(r"\b(19|20)\d{2}\b", js)
        if m:
            entry["year"] = m.group(0)

    # 2) 正文起点（abstract / keywords / 摘要），题名与作者都在它前面
    boundary = len(lines)
    for i, line in enumerate(lines[:40]):
        if re.match(r"^(a\s*b\s*s\s*t\s*r\s*a\s*c\s*t|abstract|keywords|摘\s*要)\b", line, re.I):
            boundary = i
            break
    head = lines[:boundary]

    # 3) 题名：优先 PDF 元数据（出版社写好的），否则取摘要前最长的连续几行
    meta_title = (meta.get("title") or "").strip()
    if 10 <= len(meta_title) <= 200 and "untitled" not in meta_title.lower() \
            and not re.search(r"\.(pdf|docx?|tex)$", meta_title, re.I) \
            and not re.search(r"microsoft word|document\d*", meta_title, re.I):
        entry["title"] = meta_title
    if not entry["title"]:
        cand = [l for l in head if 12 <= len(l) <= 200 and _en_line_ok(l)]
        if cand:
            longest = max(cand, key=len)
            idx = head.index(longest)
            block = [longest]
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(head) and head[j] in cand and len(head[j]) >= 12:
                    block.append(head[j])
            entry["title"] = " ".join(block)

    # 4) 作者行：带单位上标的（期刊样式），或题名后连续的英文人名行（会议/论文样式）
    for line in head:
        if re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", line) and re.search(r"\b[a-z]\b\s*(,|$)", line):
            raw = re.sub(r"\s+[a-z∗*]\s*(?=,|$)", "", line)
            names = [n.strip(" ,") for n in re.split(r",| and ", raw) if n.strip(" ,")]
            if names and all(_EN_NAME.match(n) for n in names):
                entry["authors"] = names
                break
    if not entry["authors"] and entry["title"]:
        start = 0
        for i, line in enumerate(head):
            if norm_title(line) and norm_title(line) in norm_title(entry["title"]):
                start = i + 1
        picked: list[str] = []
        for line in head[start:start + 12]:
            name = re.sub(r"\s*[\d*∗†‡§,]+$", "", line).strip()
            if _EN_NAME.match(name):
                picked.append(name)
                continue
            if "@" in line or re.search(r"universit|college|institut|department|laborator",
                                        line, re.I):
                continue            # 邮箱/单位：跳过继续找后面的作者
            if picked and (len(line) > 60 or re.search(r"[.!?]$", line)):
                break               # 已经是正文句子了，停止

        entry["authors"] = picked[:8]
    return entry


# --------------------------------------------------------------------------
# 建库
# --------------------------------------------------------------------------

_KIND_MAP = {"J": "期刊", "D": "学位论文", "M": "专著", "C": "会议", "N": "报纸",
             "R": "报告", "S": "标准", "P": "专利", "G": "汇编"}


def parse_opening_entries(raw_list: list[str]) -> list[dict]:
    """解析任务书/开题报告里已经写好的题录（优先级最高，必须引用）。"""
    out: list[dict] = []
    for raw in raw_list or []:
        text = " ".join(str(raw).split()).strip()
        if not text:
            continue
        m = re.match(r"^(.+?)[.．]\s*(.+?)\[([A-Za-z]{1,2})(?:/[A-Z]{2})?\](.*)$", text)
        if m:
            authors, title, code, tail = m.group(1), m.group(2), m.group(3).upper(), m.group(4)
            kind = _KIND_MAP.get(code, "")
        else:
            authors, title, kind, tail = "", text, "", ""
        body = tail.lstrip(".． ").rstrip(".")
        year = ""
        my = re.search(r"((?:19|20)\d{2})", body)
        if my:
            year = my.group(1)
        volume = issue = pages = ""
        mv = re.search(r",\s*(\d+)\s*(?:\((\d+)\))?\s*:\s*([\d\-–]+)", body)
        if mv:
            volume, issue, pages = mv.group(1), mv.group(2) or "", mv.group(3)
        source = ""
        ms = re.match(r"^([^,，.]+)", body)
        if ms and ms.group(1).strip() and ms.group(1).strip() != year:
            source = ms.group(1).strip()
        entry = {
            "id": None, "origin": "opening", "tier": "opening",
            "title": title.strip(), "kind": kind, "year": year,
            "authors": _clean_authors([a for a in re.split(r"[,，、;；]\s*", authors) if a.strip()]),
            "source": source, "volume": volume, "issue": issue, "pages": pages,
            "cited": "", "keywords": "", "cnki": "", "category": "", "file": "",
            "quote": "", "abstract": "", "chapter": "", "raw": text,
            "provenance": {"raw": "开题报告/任务书题录"},
        }
        entry["lang"] = "en" if _looks_english(text) else "zh"
        entry["status"] = "complete" if (entry["authors"] or entry["lang"] == "en") \
            else "missing_author"
        out.append(entry)
    return out


def _match_opening_refs(entries: list[dict], opening: list[str]) -> None:
    """用开题报告里已格式化的题录补作者/刊名（题名精确匹配才用）。"""
    parsed = []
    for raw in opening or []:
        text = " ".join(str(raw).split())
        m = re.match(r"^(.+?)[.．]\s*(.+?)\[(J|D|M|C|N|R|S|P)\]", text)
        if m:
            parsed.append({"authors": m.group(1), "title": m.group(2), "raw": text})
    for entry in entries:
        if entry["authors"]:
            continue
        key = norm_title(entry["title"])
        if not key:
            continue
        for item in parsed:
            other = norm_title(item["title"])
            if not other:
                continue
            if other == key or (len(other) >= 10 and (other.startswith(key[:12]) or key.startswith(other[:12]))):
                names = re.split(r"[,，、]\s*", item["authors"])
                if len(names) > 6:
                    names = names[:6]
                entry["authors"] = _clean_authors(names)
                entry["provenance"]["authors"] = "开题报告题录"
                if not entry["source"]:
                    m = re.search(r"\[[JJDMC]\]\.\s*([^.．]+)", item["raw"])
                    if m:
                        entry["source"] = m.group(1).strip(" .．")
                        entry["provenance"]["source"] = "开题报告题录"
                break


def _complete(entry: dict) -> str:
    """complete / complete_link / missing_author / missing_source

    实在查不到刊名/学校时，允许用知网链接以 [J/OL]、[D/OL] 形式著录（status=complete_link）：
    条目仍可核对、不编造刊名；缺作者的条目永远不算齐全。
    """
    if not entry.get("authors"):
        return "missing_author"
    if entry.get("source"):
        return "complete"
    if entry.get("cnki"):
        return "complete_link"
    return "missing_source"


def harvest(root: Path, cfg: dict) -> dict:
    rcfg = _refs_cfg(cfg)
    zh_dir = root / rcfg.get("zh_source_dir", DEFAULT_ZH_DIR)
    min_total = int(rcfg.get("min_total", DEFAULT_MIN_TOTAL))

    mds = [p for p in sorted(zh_dir.glob("*.md")) if not re.match(r"^readme", p.name, re.I)] \
        if zh_dir.is_dir() else []
    opens = [p for p in zh_dir.glob("*") if p.suffix.lower() in (".pdf", ".caj")] \
        if zh_dir.is_dir() else []
    pdf_dirs = [zh_dir / "pdf"] if (zh_dir / "pdf").is_dir() else []

    entries: list[dict] = []
    for md in mds:
        try:
            entries.append(parse_rec_md(md))
        except Exception as e:  # 单篇坏了不要连累整库
            print(f"[警告] 解析失败已跳过：{md.name}（{e}）", file=sys.stderr)

    if zh_dir.is_dir():
        known_files = {e.get("pdf_rel", "") for e in entries}
        known_seqs = {e.get("seq") for e in entries if e.get("seq") is not None}
        known_titles = {norm_title(e.get("title")) for e in entries}
        for p in opens:
            seq = _seq_of(p.name)
            # 同一篇的正文 md 与扫描件按序号去重，不重复计入文献库
            if p.name in known_files or (seq is not None and seq in known_seqs):
                continue
            if norm_title(re.sub(r"^\d+-", "", p.stem)) in known_titles:
                continue
            entries.append({
                "id": None, "origin": "rec", "file": p.name, "seq": _seq_of(p.name),
                "title": re.sub(r"^\d+-", "", p.stem), "kind": "", "year": "", "cited": "",
                "keywords": "", "cnki": "", "category": "", "authors": [], "source": "",
                "volume": "", "issue": "", "pages": "", "provenance": {},
                "pdf_rel": p.name,
            })

    # PDF 首页补作者/学校
    for entry in entries:
        pdf = None
        if entry.get("pdf_rel"):
            cand = zh_dir / entry["pdf_rel"]
            if cand.is_file():
                pdf = cand
        if pdf is None and entry.get("seq") is not None:
            for d in [zh_dir, *pdf_dirs]:
                hit = sorted(d.glob(f"{entry['seq']:02d}-*.pdf")) if d.is_dir() else []
                if hit:
                    pdf = hit[0]
                    break
        if pdf is not None and not entry["authors"]:
            got = authors_from_pdf(_pdf_text(pdf, pages=3), entry["title"], entry["kind"])
            if got.get("authors"):
                entry["authors"] = got["authors"]
                entry["provenance"]["authors"] = f"PDF:{pdf.name}"
            if got.get("source") and not entry["source"]:
                entry["source"] = got["source"]
                entry["provenance"]["source"] = f"PDF:{pdf.name}"
        if pdf is not None:
            entry["pdf"] = str(pdf.relative_to(root))

    # 开题报告/任务书题录：优先级最高，必须全部进参考文献
    student_path = root / ".work" / "student.json"
    opening_raw: list[str] = []
    school = ""
    if student_path.is_file():
        try:
            sj = json.loads(student_path.read_text(encoding="utf-8-sig"))
            opening_raw = sj.get("references") or []
            school = (sj.get("school") or "").strip()
        except Exception:
            opening_raw = []
    opening_entries = parse_opening_entries(opening_raw)
    # 与推荐文献同一篇时，把推荐理由/摘要挂到开题题录上，避免重复计数
    opening_keys = {norm_title(e["title"]) for e in opening_entries}
    merged_rec: list[dict] = []
    for entry in entries:
        key = norm_title(entry.get("title"))
        twin = next((o for o in opening_entries if norm_title(o["title"]) == key), None) \
            if key in opening_keys else None
        if twin is None:
            merged_rec.append(entry)
            continue
        for field in ("quote", "abstract", "chapter", "keywords", "category", "cnki",
                      "cited", "pdf"):
            if entry.get(field) and not twin.get(field):
                twin[field] = entry[field]
        twin["provenance"]["from_rec"] = entry.get("file") or ""
    entries = merged_rec
    _match_opening_refs(entries, opening_raw)

    # 英文：外文原文
    en_entries: list[dict] = []
    globs = rcfg.get("en_source_glob") or list(DEFAULT_EN_GLOBS)
    for pattern in globs:
        for pdf in sorted(root.glob(pattern)):
            if pdf.is_file():
                en_entries.append(parse_en_pdf(pdf))
    en_override = refs_dir(root) / "en-source.json"
    if en_override.is_file():
        try:
            fixed = json.loads(en_override.read_text(encoding="utf-8-sig"))
            if isinstance(fixed, dict) and fixed.get("title"):
                if en_entries:
                    en_entries[0].update({k: v for k, v in fixed.items() if v})
                    en_entries[0]["needs_review"] = False
                    en_entries[0]["provenance"]["human"] = "en-source.json"
                else:
                    fixed.setdefault("id", "E1")
                    fixed.setdefault("origin", "en_source")
                    fixed["needs_review"] = False
                    en_entries.append(fixed)
        except Exception as e:
            print(f"[警告] en-source.json 不可读，忽略：{e}", file=sys.stderr)

    # 开题题录里的英文条目与外文原文是同一篇时，只保留外文原文那条
    if opening_entries and en_entries:
        en_titles = [norm_title(e.get("title")) for e in en_entries if e.get("title")]
        kept_open: list[dict] = []
        for o in opening_entries:
            okey = norm_title(o.get("title"))
            twin = None
            if o.get("lang") == "en" and okey:
                twin = next((e for e in en_entries
                             if norm_title(e.get("title"))
                             and (norm_title(e["title"]) in okey or okey in norm_title(e["title"]))),
                            None)
            if twin is not None:
                twin["also_in_opening"] = o.get("raw")
                continue
            kept_open.append(o)
        opening_entries = kept_open
    for i, entry in enumerate(opening_entries, 1):
        entry["id"] = f"O{i}"

    # 已有的补录结果先合并一遍，避免重复跑 merge 丢字段
    for i, entry in enumerate(entries, 1):
        entry["id"] = entry["id"] or i
    merge_meta_results(entries, refs_dir(root) / "meta-results.json", quiet=True, en=en_entries)
    for entry in entries:
        entry["status"] = _complete(entry)

    library = {
        "repo": root.name,
        "harvested_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "zh_dir": str(zh_dir.relative_to(root)) if zh_dir.is_dir() else None,
            "en": [e["file"] for e in en_entries],
            "opening_refs": len(opening_entries),
        },
        "school": school,
        "rules": {
            "min_total": min_total,
            "max_total": int(rcfg.get("max_total", DEFAULT_MAX_TOTAL)),
            "require_english": bool(rcfg.get("require_english", True)),
            "max_english": _max_english_for(rcfg, school),
            "require_opening": bool(rcfg.get("require_opening", True)),
        },
        "opening": opening_entries,
        "zh": entries,
        "en": en_entries,
    }
    library["stats"] = _stats(library)

    out = refs_dir(root)
    _write_json(out / "library.json", library)
    (out / "library.md").write_text(_library_md(library), encoding="utf-8")
    (out / "missing-meta.md").write_text(_missing_md(library), encoding="utf-8")
    (out / "notes.md").write_text(_notes_md(library), encoding="utf-8")
    (out / "opening-sources.md").write_text(_opening_sources_md(library), encoding="utf-8")
    raw_blocks = []
    for e in en_entries:
        pdf = root / "开题材料" / str(e.get("file") or "")
        if pdf.is_file():
            raw_blocks.append(f"### {e['file']}\n{_pdf_text(pdf, pages=1)[:1500]}")
    if raw_blocks:
        (out / "en-source-raw.md").write_text("\n\n".join(raw_blocks), encoding="utf-8")
    if not (out / "meta-results.json").exists():
        _write_json(out / "meta-results.json", _meta_template(library))
    return library


def _max_english_for(rcfg: dict, school: str) -> int:
    """英文配额按学校取：河北科技师范学院只要外文原文 1 篇。"""
    by_school = rcfg.get("english_by_school") or {}
    if school and school in by_school:
        return int(by_school[school])
    for name, quota in by_school.items():
        if name and school and (name in school or school in name):
            return int(quota)
    return int(rcfg.get("max_english", DEFAULT_MAX_ENGLISH))


def _stats(library: dict) -> dict:
    zh = library.get("zh") or []
    en = library.get("en") or []
    opening = library.get("opening") or []
    by = {"complete": 0, "complete_link": 0, "missing_author": 0, "missing_source": 0}
    for e in zh:
        by[e.get("status", "missing_author")] = by.get(e.get("status", "missing_author"), 0) + 1
    rules = library.get("rules") or {}
    op_zh = [e for e in opening if e.get("lang") != "en"]
    op_en = [e for e in opening if e.get("lang") == "en"]
    return {
        "opening_total": len(opening),
        "opening_zh": len(op_zh),
        "opening_en": len(op_en),
        "opening_complete": sum(1 for e in opening if e.get("status") == "complete"),
        "zh_total": len(zh),
        "zh_complete": by["complete"] + by["complete_link"],
        "zh_source_link": by["complete_link"],
        "zh_missing_author": by["missing_author"],
        "zh_missing_source": by["missing_source"],
        "en_total": len(en),
        "en_ready": sum(1 for e in en
                        if e.get("title") and e.get("authors") and e.get("source")),
        "min_total": rules.get("min_total", DEFAULT_MIN_TOTAL),
        "max_total": rules.get("max_total", DEFAULT_MAX_TOTAL),
        "max_english": rules.get("max_english", DEFAULT_MAX_ENGLISH),
        "require_opening": rules.get("require_opening", True),
    }


# --------------------------------------------------------------------------
# 题录渲染（GB/T 7714）
# --------------------------------------------------------------------------

def render_zh(entry: dict) -> str:
    if entry.get("origin") == "opening" and entry.get("raw"):
        return entry["raw"]          # 开题报告里已经写好的题录，原样保留
    authors = entry.get("authors") or []
    head = ", ".join(authors[:3]) + (", 等" if len(authors) > 3 else "")
    kind = "D" if entry.get("kind") in ("硕士", "博士", "学位论文") else "J"
    title = entry.get("title") or ""
    source = entry.get("source") or ""
    year = entry.get("year") or ""
    body = f"{head}. " if head else ""
    if not source and entry.get("cnki"):
        return f"{body}{title}[{kind}/OL]. 中国知网, {year or 'n.d.'}. {entry['cnki']}."
    body += f"{title}[{kind}]. "
    if source and year:
        body += f"{source}, {year}"
    elif source:
        body += source
    else:
        body += year
    if kind == "J":
        if entry.get("volume"):
            body += f", {entry['volume']}"
            if entry.get("issue"):
                body += f"({entry['issue']})"
        elif entry.get("issue"):
            body += f", ({entry['issue']})"
        if entry.get("pages"):
            body += f": {entry['pages']}"
    return body + "."


def render_en(entry: dict) -> str:
    def fmt(name: str) -> str:
        parts = [p for p in name.split() if p]
        if len(parts) == 1:
            return parts[0].upper()
        return f"{parts[-1].upper()} {''.join(p[0].upper() for p in parts[:-1])}"

    authors = [fmt(a) for a in (entry.get("authors") or [])]
    head = ", ".join(authors[:3]) + (", et al" if len(authors) > 3 else "")
    body = f"{head}. " if head else ""
    body += f"{entry.get('title') or ''}[J]. {entry.get('source') or ''}"
    if entry.get("year"):
        body += f", {entry['year']}"
    if entry.get("volume"):
        body += f", {entry['volume']}"
        if entry.get("issue"):
            body += f"({entry['issue']})"
    if entry.get("pages"):
        body += f": {entry['pages']}"
    return body + "."


def _library_md(library: dict) -> str:
    st = library.get("stats") or {}
    lines = [f"# 参考文献库（{library.get('repo')}）", "",
             f"- 建库时间：{library.get('harvested_at')}　学校：{library.get('school') or '未识别'}",
             f"- 开题报告/任务书题录：{st.get('opening_total')} 条"
             f"（中文 {st.get('opening_zh')}、英文 {st.get('opening_en')}）——**必须全部引用**",
             f"- 仓库推荐文献：{st.get('zh_total')} 篇（题录齐全 {st.get('zh_complete')}，"
             f"其中缺出版项按链接著录 {st.get('zh_source_link', 0)}，"
             f"缺作者 {st.get('zh_missing_author')}，缺来源 {st.get('zh_missing_source')}）",
             f"- 英文：外文原文 {st.get('en_total')} 篇（可直接引用 {st.get('en_ready')}）"
             f"　英文配额 ≤ {st.get('max_english')} 篇",
             f"- 全文条数区间：{st.get('min_total')}–{st.get('max_total')} 条", "",
             "## 一、开题报告/任务书题录（优先，必须全部用上）", ""]
    for e in library.get("opening") or []:
        flag = "" if e.get("status") == "complete" else "　⚠ 题录不完整，需核对原文"
        lines.append(f"[{e['id']}] {render_zh(e)}{flag}")
        if e.get("chapter"):
            lines.append(f"    建议引用位置：{e['chapter']}")
    lines += ["", "## 二、仓库推荐文献（论文/论文推荐）", ""]
    for e in library.get("zh") or []:
        if e.get("status") == "complete":
            flag = ""
        elif e.get("status") == "complete_link":
            flag = "　（缺刊名/学校，按 [J/OL] 或 [D/OL] + 知网链接著录）"
        else:
            flag = f"　⚠ {e.get('status')}"
        lines.append(f"[{e['id']}] {render_zh(e)}{flag}")
        if e.get("chapter"):
            lines.append(f"    建议引用位置：{e['chapter']}")
    lines += ["", "## 三、英文（开题材料 外文原文）", ""]
    for e in library.get("en") or []:
        lines.append(f"[{e['id']}] {render_en(e)}")
        if e.get("needs_review"):
            lines.append("    ⚠ 自动识别结果待确认（.work/refs/en-source.json）")
    return "\n".join(lines) + "\n"


def _opening_sources_md(library: dict) -> str:
    """开题题录必须优先采用：这里列出待联网检索原文的清单。"""
    lines = ["# 开题题录原文检索清单", "",
             "任务书/开题报告里列的参考文献必须优先采用。逐条在知网检索原文，",
             "把「是否取到原文 + 链接」记进 `.work/refs/opening-sources.json`：",
             '`[{"id": "O1", "title": "题名", "url": "https://kns.cnki.net/...", "got": true}]`',
             "取不到原文的，在交付报告里点名，不要拿相近的另一篇顶替。", ""]
    for e in library.get("opening") or []:
        lines += [f"## [{e.get('id')}] {e.get('title')}",
                  f"- 题录：{e.get('raw') or ''}",
                  f"- 类型/年份：{e.get('kind') or '?'} / {e.get('year') or '?'}"
                  f"　语言：{'英文' if e.get('lang') == 'en' else '中文'}",
                  "- 知网检索：https://kns.cnki.net/kns8s/search 按上面的题名检索原文",
                  "- 状态：待检索"]
    return "\n".join(lines) + "\n"


def _missing_md(library: dict) -> str:
    zh = [e for e in (library.get("zh") or [])
          if e.get("status") not in ("complete", "complete_link")]
    op_gaps = [e for e in (library.get("opening") or []) if e.get("status") != "complete"]
    lines = ["# 题录缺口（需要补录）", "",
             f"仓库：{library.get('repo')}　推荐文献缺项 {len(zh)} 篇"
             f"　开题题录不完整 {len(op_gaps)} 条", "",
             "补录方式：先**读仓库里已经下载好的文献本身**（每篇的 pdf / caj / md）；",
             "读不出来可以联网按题名检索核对题录（只补元数据、不换文献）。",
             "把作者/来源/年卷期页抄进 `.work/refs/meta-results.json`（已按缺口生成好空行），",
             "再跑 `refs merge`。",
             "题名以库内为准，`confidence` 写 `exact`；文献里确实没有的字段就留空，",
             "留空的期刊/学位论文会按 [J/OL]、[D/OL] + 知网链接著录。", ""]
    if op_gaps:
        lines += ["", "## 开题题录待核对（题录本身已在库里，只需核对原文）"]
        for e in op_gaps:
            lines += [f"## [{e.get('id')}] {e.get('title')}",
                      f"- 原文题录：{e.get('raw') or ''}"]
    for e in zh:
        need = []
        if not e.get("authors"):
            need.append("作者")
        if not e.get("source"):
            need.append("来源（刊名/学校）")
        local = e.get("pdf") or e.get("file") or "（仓库里没有可读文件）"
        lines += [f"## [{e['id']}] {e.get('title')}",
                  f"- 缺：{'、'.join(need)}；类型：{e.get('kind') or '未知'}；年份：{e.get('year') or '未知'}",
                  f"- 本地文件：{local}",
                  f"- 知网链接（可打开核对原文）：{e.get('cnki') or '（无，需按题名检索）'}"]
    en_gaps = [e for e in (library.get("en") or [])
               if not (e.get("title") and e.get("authors") and e.get("source"))]
    if en_gaps:
        lines += ["", "## 英文（开题材料 外文原文）"]
        for e in en_gaps:
            miss = [k for k in ("title", "authors", "source") if not e.get(k)]
            lines += [f"## [{e.get('id')}] {e.get('file')}",
                      f"- 缺：{'、'.join({'title': '题名', 'authors': '作者', 'source': '刊名/会议名'}[k] for k in miss)}",
                      f"- 自动识别结果：{e.get('title') or '（未识别）'}｜"
                      f"{', '.join(e.get('authors') or []) or '（未识别作者）'}",
                      f"- 原始首页文本：.work/refs/en-source-raw.md"]
    lines += ["", "meta-results.json 单条格式：", "```json",
              '[{"id": 1, "title": "题名", "authors": "张三, 李四", "source": "计算机工程",',
              '  "year": "2023", "volume": "51", "issue": "6", "pages": "1-10",',
              '  "url": "PDF:01-xxx.pdf", "confidence": "exact"}]', "```"]
    return "\n".join(lines) + "\n"


def _notes_md(library: dict) -> str:
    """给写作阶段用的证据摘要：每篇的推荐句 + 摘要，不从网络补。"""
    lines = [f"# 文献要点（{library.get('repo')}）", "",
             "写作时按这里的内容支撑论断；题录本身见 library.md。", ""]
    for e in library.get("opening") or []:
        lines += [f"## [{e['id']}] {e.get('title')}（开题报告已列，必须引用）",
                  f"- 题录：{e.get('raw') or ''}"]
        if e.get("quote"):
            lines.append(f"- 可引原句：{e['quote']}")
        if e.get("abstract"):
            lines.append(f"- 摘要：{e['abstract'][:400]}")
        lines.append("")
    for e in library.get("zh") or []:
        lines += [f"## [{e['id']}] {e.get('title')}",
                  f"- 类型/年份：{e.get('kind') or '?'} / {e.get('year') or '?'}"
                  f"　建议引用位置：{e.get('chapter') or '（未标注）'}"]
        if e.get("quote"):
            lines.append(f"- 可引原句：{e['quote']}")
        if e.get("abstract"):
            lines.append(f"- 摘要：{e['abstract'][:400]}")
        lines.append("")
    for e in library.get("en") or []:
        lines += [f"## [{e.get('id')}] {e.get('title')}", "- 外文原文，译文见开题材料/外文翻译。", ""]
    return "\n".join(lines)


def _meta_template(library: dict) -> list[dict]:
    """按缺口生成待填的补录模板，Agent 只需填字段。"""
    rows = []
    for e in library.get("zh") or []:
        if e.get("status") == "complete":
            continue
        rows.append({"id": e["id"], "title": e.get("title"), "authors": "",
                     "source": "", "year": e.get("year") or "", "volume": "", "issue": "",
                     "pages": "", "url": "", "confidence": ""})
    for e in library.get("en") or []:
        if e.get("title") and e.get("authors") and e.get("source"):
            continue
        rows.append({"id": e.get("id"), "title": e.get("title") or "", "authors": "",
                     "source": "", "year": e.get("year") or "", "volume": "", "issue": "",
                     "pages": "", "url": "", "confidence": ""})
    return rows


# --------------------------------------------------------------------------
# 合并补录
# --------------------------------------------------------------------------

def merge_meta_results(entries: list[dict], path: Path, quiet: bool = False,
                       en: list[dict] | None = None) -> dict:
    """把补录结果并入条目（含外文原文那一条）。题名对不上就丢弃，不猜。"""
    report = {"applied": 0, "rejected": []}
    pool = list(entries) + list(en or [])
    if not path.is_file():
        return report
    try:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise yx.YunxiaoError(f"meta-results.json 不可读：{e}") from e
    if not isinstance(rows, list):
        raise yx.YunxiaoError("meta-results.json 应是数组")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not any(str(row.get(k) or "").strip() for k in
                   ("authors", "source", "volume", "issue", "pages")):
            continue  # 模板里还没填的空行
        idx = row.get("id")
        title = norm_title(row.get("title") or "")
        target = None
        for e in pool:
            if idx is not None and str(e.get("id")) == str(idx):
                target = e
                break
        if target is None and title:
            for e in pool:
                if norm_title(e.get("title")) == title:
                    target = e
                    break
        if target is None:
            report["rejected"].append({"id": idx, "title": row.get("title"), "why": "库里没有这条题名"})
            continue
        is_en = target.get("origin") == "en_source"
        if title and not is_en and norm_title(target.get("title")) != title:
            report["rejected"].append({"id": idx, "title": row.get("title"),
                                       "why": "题名与库里条目不匹配，未采用"})
            continue
        if is_en and title:
            target["title"] = row.get("title")   # 外文原文的题名允许人工改正
        if str(row.get("confidence", "exact")).lower() not in ("exact", "exact_title", "ok"):
            report["rejected"].append({"id": idx, "title": row.get("title"),
                                       "why": f"confidence={row.get('confidence')}，非精确匹配"})
            continue
        if row.get("authors") and not target.get("authors"):
            names = [n for n in re.split(r"[,，、;；]\s*", str(row["authors"])) if n.strip()]
            target["authors"] = _clean_authors(names)
            target["provenance"]["authors"] = f"补录:{row.get('url') or 'meta-results'}"
        for key in ("source", "year", "volume", "issue", "pages"):
            val = str(row.get(key) or "").strip()
            if val and not target.get(key):
                target[key] = val
                target["provenance"][key] = f"补录:{row.get('url') or 'meta-results'}"
        target["status"] = _complete(target)
        report["applied"] += 1
    if not quiet:
        print(f"补录合并：采用 {report['applied']} 条，拒绝 {len(report['rejected'])} 条")
        for r in report["rejected"]:
            print(f"  - [{r['id']}] {r['why']}：{r['title']}")
    return report


def merge(root: Path) -> int:
    lib_path = refs_dir(root) / "library.json"
    if not lib_path.is_file():
        print("[错误] 还没有文献库，先跑 refs harvest", file=sys.stderr)
        return 1
    library = json.loads(lib_path.read_text(encoding="utf-8-sig"))
    entries = library.get("zh") or []
    report = merge_meta_results(entries, refs_dir(root) / "meta-results.json",
                               en=library.get("en") or [])
    library["zh"] = entries
    library["stats"] = _stats(library)
    library["merged_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(lib_path, library)
    (refs_dir(root) / "library.md").write_text(_library_md(library), encoding="utf-8")
    (refs_dir(root) / "missing-meta.md").write_text(_missing_md(library), encoding="utf-8")
    st = library["stats"]
    print(f"文献库：中文 {st['zh_total']} 篇（齐全 {st['zh_complete']}，"
          f"缺作者 {st['zh_missing_author']}，缺来源 {st['zh_missing_source']}）；"
          f"英文 {st['en_total']} 篇")
    return 0 if not report["rejected"] or report["applied"] else 0


# --------------------------------------------------------------------------
# 稿件校验（发布闸门）
# --------------------------------------------------------------------------

def parse_manuscript_refs(text: str) -> tuple[list[dict], str]:
    lines = text.splitlines()
    start = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if re.match(r"^#{1,4}\s", s) and "参考文献" in s:
            start = i + 1
            break
    if start is None:
        return [], ""
    entries = []
    for raw in lines[start:]:
        s = raw.strip()
        if re.match(r"^#{1,4}\s", s):
            break
        m = re.match(r"^\[(\d{1,3})\]\s*(.+)$", s)
        if m:
            entries.append({"n": int(m.group(1)), "text": m.group(2).strip()})
    body = "\n".join(lines[: start - 1]) if start else text
    return entries, body


def _looks_english(text: str) -> bool:
    """条目通篇没有中文、且有若干英文单词时，视为英文文献（允许 1–2 篇库外英文）。"""
    if re.search("[" + chr(92) + "u4e00-" + chr(92) + "u9fa5]", text):
        return False
    words = re.findall(r"[A-Za-z]{3,}", text)
    return len(words) >= 4


def _cites_in_body(body: str) -> set[int]:
    cited: set[int] = set()
    for m in re.finditer(r"\[(\d{1,3}(?:\s*[,，\-–~]\s*\d{1,3})*)\]", body):
        for part in re.split(r"[,，]", m.group(1)):
            part = part.strip()
            if re.fullmatch(r"\d{1,3}", part):
                cited.add(int(part))
            else:
                rng = re.split(r"[\-–~]", part)
                if len(rng) == 2 and all(x.strip().isdigit() for x in rng):
                    a, b = int(rng[0]), int(rng[1])
                    if 0 < b - a <= 40:
                        cited.update(range(a, b + 1))
    return cited


def verify(root: Path, cfg: dict) -> tuple[bool, dict]:
    rcfg = _refs_cfg(cfg)
    lib_path = refs_dir(root) / "library.json"
    problems: list[str] = []
    if not lib_path.is_file():
        return False, {"ok": False, "problems": ["没有文献库（.work/refs/library.json），先跑 refs harvest"]}
    library = json.loads(lib_path.read_text(encoding="utf-8-sig"))
    rules = library.get("rules") or {}
    min_total = int(rcfg.get("min_total", rules.get("min_total", DEFAULT_MIN_TOTAL)))
    max_total = int(rcfg.get("max_total", rules.get("max_total", DEFAULT_MAX_TOTAL)))
    require_en = bool(rcfg.get("require_english", rules.get("require_english", True)))
    require_opening = bool(rcfg.get("require_opening", rules.get("require_opening", True)))

    ms = root / ".work" / "manuscript.md"
    if not ms.is_file():
        return False, {"ok": False, "problems": ["找不到 manuscript.md，论文正文还没写"]}
    entries, body = parse_manuscript_refs(ms.read_text(encoding="utf-8-sig"))
    if not entries:
        return False, {"ok": False, "problems": ["稿件里没有「参考文献」区，或条目不是 [n] 开头"]}

    total = len(entries)
    if total < min_total:
        problems.append(f"参考文献只有 {total} 条，少于要求的 {min_total} 条")
    if total > max_total:
        problems.append(f"参考文献 {total} 条，超过上限 {max_total} 条")

    nums = [e["n"] for e in entries]
    if nums != list(range(1, total + 1)):
        problems.append(f"参考文献编号不连续（实际 {nums[:5]}…{nums[-3:]}），应为 1–{total}")

    zh = library.get("zh") or []
    en = library.get("en") or []
    opening = library.get("opening") or []
    op_zh = [e for e in opening if e.get("lang") != "en"]
    op_en = [e for e in opening if e.get("lang") == "en"]
    zh_keys = [(e["id"], norm_title(e.get("title")), e) for e in zh + op_zh]
    en_keys = [(e["id"], norm_title(e.get("title")), e)
               for e in en + op_en if e.get("title")]

    matched_zh, matched_en, unmatched = [], [], []
    for item in entries:
        nkey = norm_title(item["text"])
        hit = None
        for eid, tkey, e in en_keys:
            if tkey and len(tkey) >= 12 and tkey in nkey:
                hit = ("en", eid, e)
                break
        if hit is None:
            for eid, tkey, e in zh_keys:
                if tkey and len(tkey) >= 6 and tkey in nkey:
                    hit = ("zh", eid, e)
                    break
        if hit is None:
            unmatched.append(item)
        elif hit[0] == "en":
            matched_en.append((item, hit[2]))
        else:
            matched_zh.append((item, hit[2]))

    # 英文条目：开题材料那篇必须有；另允许 1–2 篇库外英文（如经典文献），合计不超过上限
    extra_en = [i for i in unmatched if _looks_english(i["text"])]
    unmatched = [i for i in unmatched if not _looks_english(i["text"])]
    en_total = len(matched_en) + len(extra_en)
    max_en = int(rcfg.get("max_english", rules.get("max_english", DEFAULT_MAX_ENGLISH)))
    en_from_source = [e for _, e in matched_en if e.get("origin") == "en_source"]

    # 开题报告/任务书里列的中文题录必须全部用上
    cited_keys = [norm_title(i["text"]) for i in entries]
    def _cited(title: str) -> bool:
        key = norm_title(title)
        return bool(key) and any(key in c for c in cited_keys)

    missing_opening = [e for e in op_zh if e.get("title") and not _cited(e["title"])]
    if require_opening and missing_opening:
        problems.append(f"开题报告里列的 {len(missing_opening)} 条参考文献没有引用（必须优先采用）："
                        + "；".join(str(e.get("title"))[:26] for e in missing_opening[:4]))

    if unmatched:
        sample = "；".join(f"[{i['n']}] {i['text'][:40]}" for i in unmatched[:5])
        problems.append(f"{len(unmatched)} 条中文参考文献不在仓库文献库里"
                        f"（中文只能来自 论文/论文推荐）：{sample}")
    if require_en and not en_from_source:
        problems.append("没有引用开题材料外文原文那一篇（英文文献必须包含外文原文）")
    if require_en and en:
        gaps = [e for e in en if not (e.get("title") and e.get("authors") and e.get("source"))]
        if gaps:
            problems.append("外文原文的题录还没补全（题名/作者/刊名缺一项）："
                            + "；".join(str(e.get("file")) for e in gaps[:3])
                            + "　补进 .work/refs/meta-results.json 后 refs merge")
    if en_total > max_en:
        problems.append(f"英文文献 {en_total} 条，超过上限 {max_en} 条"
                        f"（开题材料那篇必须在内；其余英文最多 {max(0, max_en - 1)} 篇）")

    require_authors = bool(rcfg.get("require_authors", rules.get("require_authors", False)))
    authorless = [e for _, e in matched_zh if not e.get("authors")]
    warnings: list[str] = []
    if authorless:
        msg = (f"{len(authorless)} 条中文文献缺作者（仓库里只有 md 题录、没有 PDF）："
               + "；".join(str(e.get("title"))[:24] for e in authorless[:3]))
        if require_authors:
            problems.append(msg + "　补录后再 refs merge")
        else:
            warnings.append(msg + "　按 [D/OL]/[J/OL] 链接著录，交付报告需点名")

    headless = [i for i in entries if not re.match(r"^.{2,40}?[.．]\s*\S", i["text"])]
    if headless:
        problems.append(f"{len(headless)} 条参考文献没写作者（条目应以「作者. 题名」开头）："
                        + "；".join(f"[{i['n']}] {i['text'][:24]}" for i in headless[:3]))

    cited = _cites_in_body(body)
    ghost = sorted(n for n in cited if n > total)
    if ghost:
        problems.append(f"正文引用了不存在的编号 {ghost[:6]}")

    report = {
        "ok": not problems,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "total": total, "min_total": min_total,
        "zh_cited": len(matched_zh),
        "en_cited": en_total, "en_from_source": len(en_from_source),
        "en_extra": len(extra_en) + len(matched_en) - len(en_from_source),
        "max_english": max_en, "max_total": max_total,
        "opening_total": len(opening), "opening_zh": len(op_zh),
        "opening_cited": len(op_zh) - len(missing_opening),
        "library": {"zh_total": len(zh),
                    "zh_complete": sum(1 for e in zh
                                       if e.get("status") in ("complete", "complete_link")),
                    "zh_source_link": sum(1 for e in zh if e.get("status") == "complete_link"),
                    "en_total": len(en)},
        "problems": problems,
        "warnings": warnings,
        "unmatched": [{"n": i["n"], "text": i["text"][:120]} for i in unmatched],
        "uncited_library": [e.get("title") for e in zh
                            if e.get("status") == "complete"
                            and not any(norm_title(e.get("title")) in norm_title(x["text"]) for x in entries)],
        "body_cites": len(cited),
    }
    _write_json(refs_dir(root) / "verify.json", report)
    return report["ok"], report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def status(root: Path, cfg: dict) -> int:
    lib_path = refs_dir(root) / "library.json"
    if not lib_path.is_file():
        print("文献库：未建（先跑 refs harvest）")
        return 0
    library = json.loads(lib_path.read_text(encoding="utf-8-sig"))
    st = library.get("stats") or {}
    print(f"文献库：{library.get('repo')}  建库 {library.get('harvested_at')}")
    print(f"  开题题录 {st.get('opening_total')} 条"
          f"（中文 {st.get('opening_zh')}、英文 {st.get('opening_en')}）——必须全部引用")
    print(f"  中文 {st.get('zh_total')} 篇：齐全 {st.get('zh_complete')}"
          f"（缺出版项按链接著录 {st.get('zh_source_link', 0)}），"
          f"缺作者 {st.get('zh_missing_author')}，缺来源 {st.get('zh_missing_source')}")
    print(f"  英文 {st.get('en_total')} 篇：可直接引用 {st.get('en_ready')}")
    print(f"  稿件要求：全文 {st.get('min_total')}–{st.get('max_total')} 条，"
          f"英文 ≤ {st.get('max_english')} 篇（必须含外文原文），开题题录全部要用上")
    verify_path = refs_dir(root) / "verify.json"
    if verify_path.is_file():
        v = json.loads(verify_path.read_text(encoding="utf-8-sig"))
        flag = "通过" if v.get("ok") else "未通过"
        print(f"  最近一次稿件校验：{flag}（{v.get('checked_at')}，共 {v.get('total')} 条）")
        for p in v.get("problems") or []:
            print(f"    - {p}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="参考文献库（仓库中文文献 + 外文原文英文文献）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("harvest", "扫描仓库材料建库"), ("merge", "合并补录结果"),
                           ("verify", "校验稿件参考文献"), ("lib", "查看文献库状态")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("repo")
    args = ap.parse_args(argv)
    try:
        root = local_root(args.repo)
        cfg = yx.load_config()
        if args.cmd == "harvest":
            library = harvest(root, cfg)
            st = library["stats"]
            print(f"[文献] 中文候选 {st['zh_total']} 篇（齐全 {st['zh_complete']}，"
                  f"其中 {st['zh_source_link']} 篇缺出版项按 [J/OL] 或 [D/OL] 链接著录，"
                  f"缺作者 {st['zh_missing_author']}，缺来源 {st['zh_missing_source']}）；"
                  f"英文 {st['en_total']} 篇")
            print(f"       文献库：{refs_dir(root) / 'library.json'}")
            print(f"       稿件要求：全文 {st['min_total']}–{st['max_total']} 条，"
                  f"英文 ≤ {st['max_english']} 篇（必须含外文原文），开题题录全部要用上")
            if st["zh_missing_author"] or st["zh_missing_source"]:
                print(f"       待补录清单：{refs_dir(root) / 'missing-meta.md'}"
                      f"（补完跑 refs merge {root.name}）")
            if st["zh_total"] < st["min_total"]:
                print(f"[阻断] 仓库只有 {st['zh_total']} 篇推荐文献，凑不够 {st['min_total']} 篇；"
                      f"请先补 论文/论文推荐", file=sys.stderr)
                return EXIT_MATERIAL
            return 0
        if args.cmd == "merge":
            return merge(root)
        if args.cmd == "verify":
            ok, report = verify(root, cfg)
            for w in report.get("warnings") or []:
                print(f"[提醒] {w}", file=sys.stderr)
            if ok:
                print(f"[文献] 校验通过：共 {report['total']} 条（中文 {report['zh_cited']}，"
                      f"英文 {report['en_cited']}，其中外文原文 {report['en_from_source']}"
                      f"、额外 {report['en_extra']}），中文全部来自仓库文献库")
                return 0
            print("[阻断] 参考文献校验未通过：", file=sys.stderr)
            for p in report["problems"]:
                print(f"  - {p}", file=sys.stderr)
            print(f"  明细：{refs_dir(root) / 'verify.json'}", file=sys.stderr)
            return EXIT_GATE
        return status(root, cfg)
    except yx.YunxiaoError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
