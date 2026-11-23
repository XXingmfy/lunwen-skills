#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plagiarism.py — 联网逐句溯源查重

知网/维普/万方都没有公开 API，机构账号也接不了。这里走的是另一条路：
**把正文拆成句子，逐句拿原句去搜出处**，搜到高度相似的来源就算命中。

分工：
  脚本负责  拆句 → 排风险 → 出待查清单 → 汇总结果算重复率
  Agent 负责 真正去搜（它手上才有联网搜索能力），把结果写回 results.json

用法：
    python plagiarism.py candidates <manuscript.md> [--limit 40]
    python plagiarism.py report <工作区> [--results results.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# --------------------------------------------------------------------------
# 拆句
# --------------------------------------------------------------------------

SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")

SKIP_LINE_RE = re.compile(r"^\s*(#{1,6}\s|!\[|\||<!--|```|-\s*\[)")
FRONT_MATTER_RE = re.compile(r"^---\s*$")

# 高风险"通用表述"：查重命中的往往是这类句子
GENERIC_MARKERS = [
    "是一种", "指的是", "主要包括", "由", "组成", "分为", "随着", "近年来",
    "综上所述", "众所周知", "随着互联网", "随着信息技术的", "越来越",
    "具有重要", "起着重要作用", "起到了", "不可忽视", "日益",
    "本文首先", "本文主要", "本文通过", "本文旨在",
]

# 低风险：本系统/本项目具体实现，基本不会被别人写过
LOW_RISK_MARKERS = [
    "本系统", "本设计", "本项目", "如图", "如表", "本课题", "本文实现的",
]


def extract_prose(manuscript: str) -> str:
    lines = manuscript.splitlines()
    start = 0
    if lines and FRONT_MATTER_RE.match(lines[0]):
        for i in range(1, len(lines)):
            if FRONT_MATTER_RE.match(lines[i]):
                start = i + 1
                break
    kept = [l for l in lines[start:] if l.strip() and not SKIP_LINE_RE.match(l)]
    return "\n".join(kept)


def split_sentences(prose: str) -> list[str]:
    out: list[str] = []
    for line in prose.splitlines():
        for s in SENT_SPLIT_RE.split(line):
            s = s.strip().strip("　")
            if s:
                out.append(s)
    return out


def risk_score(sentence: str) -> int:
    score = 0
    for m in GENERIC_MARKERS:
        if m in sentence:
            score += 2
    for m in LOW_RISK_MARKERS:
        if m in sentence:
            score -= 3
    n = len(sentence)
    if n >= 60:
        score += 3
    elif n >= 40:
        score += 2
    elif n >= 25:
        score += 1
    # 带书名号/引号的多半是引用，不是抄
    if "《" in sentence or "“" in sentence:
        score -= 1
    return score


def build_candidates(manuscript: str, limit: int = 40,
                     min_chars: int = 25) -> dict[str, Any]:
    prose = extract_prose(manuscript)
    sentences = split_sentences(prose)

    items = []
    seen = set()
    for idx, s in enumerate(sentences):
        if len(s) < min_chars:
            continue
        key = re.sub(r"\s+", "", s)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "id": len(items),
            "index": idx,
            "chars": len(s),
            "risk": risk_score(s),
            "text": s,
            "query": f'"{s[:40]}"',   # 建议的搜索词：加引号精确匹配
        })

    items.sort(key=lambda x: (-x["risk"], -x["chars"]))
    picked = items[:limit]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_sentences": len(sentences),
        "checked_candidates": len(picked),
        "candidates": picked,
        "howto": (
            "对每个 candidate 用 query（或整句）做联网搜索；"
            "把结果写回 results.json，格式："
            '{"id": 0, "matches": [{"url": "...", "title": "...", '
            '"snippet": "...", "verdict": "原文照抄|改写|无匹配"}]}'
        ),
    }


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def summarize(cand: dict[str, Any], results: list[dict]) -> dict[str, Any]:
    by_id = {r["id"]: r for r in results if "id" in r}
    hits, partial, clean, unchecked = [], [], [], []

    for c in cand["candidates"]:
        r = by_id.get(c["id"])
        if not r:
            unchecked.append(c)
            continue
        verdicts = [m.get("verdict", "") for m in r.get("matches", [])]
        if "原文照抄" in verdicts:
            hits.append({**c, "matches": r.get("matches", [])})
        elif "改写" in verdicts:
            partial.append({**c, "matches": r.get("matches", [])})
        else:
            clean.append(c)

    checked = len(hits) + len(partial) + len(clean)
    dup_rate = (len(hits) / checked * 100) if checked else 0.0
    risk_rate = ((len(hits) + len(partial)) / checked * 100) if checked else 0.0

    return {
        "checked": checked,
        "unchecked": len(unchecked),
        "hits": hits,
        "partial": partial,
        "clean": clean,
        "dup_rate_pct": round(dup_rate, 2),
        "risk_rate_pct": round(risk_rate, 2),
    }


def render_report(summary: dict[str, Any], cand: dict[str, Any]) -> str:
    lines = [
        "# 联网溯源查重报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 全文句子数：{cand['total_sentences']}",
        f"- 已抽查句子：{summary['checked']}（未查 {summary['unchecked']}）",
        f"- **命中照抄：{len(summary['hits'])} 句**",
        f"- 命中改写：{len(summary['partial'])} 句",
        f"- **抽样重复率：{summary['dup_rate_pct']}%**（命中照抄 / 已查句数）",
        f"- 综合风险率：{summary['risk_rate_pct']}%（照抄 + 改写）",
        "",
        "> 这是**抽样**结果，不等于知网重复率。知网比的是它的全文库（含未公开的学位论文），",
        "> 联网溯源只能查到公开网页上的来源。两者口径不同，不能互相替代。",
        "",
    ]

    if summary["hits"]:
        lines += ["## 必须改写的句子（原文照抄）", ""]
        for i, h in enumerate(summary["hits"], 1):
            lines.append(f"### {i}. 风险 {h['risk']}｜{h['chars']} 字")
            lines.append("")
            lines.append(f"> {h['text']}")
            lines.append("")
            for m in h.get("matches", [])[:3]:
                lines.append(f"- [{m.get('title','来源')}]({m.get('url','')})")
                if m.get("snippet"):
                    lines.append(f"  - {m['snippet'][:150]}")
            lines.append("")

    if summary["partial"]:
        lines += ["## 建议改写的句子（改写搬运）", ""]
        for i, h in enumerate(summary["partial"], 1):
            lines.append(f"{i}. {h['text']}")
        lines.append("")

    if summary["clean"]:
        lines += [f"## 未查到来源（{len(summary['clean'])} 句）", ""]
        lines.append("抽样内未命中，不代表知网不命中。")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="联网逐句溯源查重")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("candidates", help="生成待查句清单")
    c.add_argument("manuscript")
    c.add_argument("--work", help="工作区，默认稿件所在目录")
    c.add_argument("--limit", type=int, default=40)
    c.add_argument("--min-chars", type=int, default=25)

    r = sub.add_parser("report", help="汇总搜索结果出报告")
    r.add_argument("work")
    r.add_argument("--results", help="results.json 路径，默认 <work>/quality/plagiarism/results.json")

    args = ap.parse_args(argv)

    if args.cmd == "candidates":
        ms = Path(args.manuscript)
        if not ms.exists():
            print(f"[错误] 找不到稿件：{ms}", file=sys.stderr)
            return 1
        cand = build_candidates(ms.read_text(encoding="utf-8-sig"),
                                limit=args.limit, min_chars=args.min_chars)
        work = Path(args.work) if args.work else ms.parent
        pdir = work / "quality" / "plagiarism"
        pdir.mkdir(parents=True, exist_ok=True)
        out = pdir / "candidates.json"
        out.write_text(json.dumps(cand, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"待查句：{cand['checked_candidates']} 条（全文 {cand['total_sentences']} 句）")
        print(f"清单：{out}")
        return 0

    work = Path(args.work)
    pdir = work / "quality" / "plagiarism"
    cand_path = pdir / "candidates.json"
    res_path = Path(args.results) if args.results else pdir / "results.json"

    if not cand_path.exists():
        print(f"[错误] 找不到 {cand_path}，先跑 candidates", file=sys.stderr)
        return 1
    if not res_path.exists():
        print(f"[错误] 找不到 {res_path}，需要先把搜索结果写进去", file=sys.stderr)
        return 1

    cand = json.loads(cand_path.read_text(encoding="utf-8-sig"))
    results = json.loads(res_path.read_text(encoding="utf-8-sig"))
    summary = summarize(cand, results)

    report = render_report(summary, cand)
    (pdir / "report.md").write_text(report, encoding="utf-8")
    (pdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已查 {summary['checked']} 句，命中照抄 {len(summary['hits'])} 句，"
          f"抽样重复率 {summary['dup_rate_pct']}%")
    print(f"报告：{pdir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
