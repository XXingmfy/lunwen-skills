#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zhuque.py — 腾讯朱雀 AIGC 文本检测（EdgeOne Makers 官方接口）

端点：POST https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify
鉴权：Authorization: Bearer <MAKERS_MODELS_KEY>

关键参数 is_merge=false：把正文切成片段，每段给 label + 置信度 + 位置。
这是"定点降重"的依据——不是拿一个总分瞎猜，而是知道哪几段拖后腿。

label 含义：0=人工  1=AI  2=疑似

用法：
    python zhuque.py check                      # 自检 Key 与连通性
    python zhuque.py detect <manuscript.md>     # 检测并落盘报告
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import requests

SKILL_DIR = Path(__file__).resolve().parent.parent
SECRETS_PATH = SKILL_DIR / "secrets.env"
CONFIG_PATH = SKILL_DIR / "config.yaml"

ENDPOINT = "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"

# 实测校准（多次对照实验确认，与官方文档描述不一致，以此为准）：
#   1 = AI 生成   2 = 人工编写   0 = 疑似/未定
# labels_ratio 是**按字符数**计算的占比；position 是 [偏移, 长度]，不是 [起点, 终点]。
# 分段粒度约 250–320 字（按句边界切），所以"定点降重"的最小单位就是这么大。
LABEL_NAMES = {0: "疑似", 1: "AI", 2: "人工"}
LABEL_AI = 1


class ZhuqueError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

def _secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    if SECRETS_PATH.exists():
        for raw in SECRETS_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_keys() -> list[str]:
    """按优先级返回全部可用 Key：主 Key 在前，备用依次在后，自动去重。"""
    se = _secrets()
    raw = [
        os_environ_get("MAKERS_MODELS_KEY"),
        os_environ_get("ZHUQUE_API_KEY"),
        se.get("MAKERS_MODELS_KEY"),
        se.get("MAKERS_MODELS_KEY_BACKUP1"),
        se.get("MAKERS_MODELS_KEY_BACKUP2"),
        se.get("MAKERS_MODELS_KEY_BACKUP3"),
    ]
    keys: list[str] = []
    for k in raw:
        k = (k or "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def mask_key(k: str) -> str:
    return f"{k[:6]}…{k[-4:]}" if k and len(k) > 12 else "***"


def get_key(required: bool = True) -> str | None:
    keys = get_keys()
    if required and not keys:
        raise ZhuqueError(
            "没有朱雀 API Key。请任选其一：\n"
            f"  1) 在 {SECRETS_PATH} 写一行： MAKERS_MODELS_KEY=xxxx\n"
            "     （可再加 MAKERS_MODELS_KEY_BACKUP1/2 作为备用，失效自动轮换）\n"
            "  2) 设置环境变量 MAKERS_MODELS_KEY\n"
            "获取方式：腾讯云 EdgeOne 控制台 → Makers → Models → API Key → 创建"
        )
    return keys[0] if keys else None


# 记住最近一次成功的 Key，下次优先用它，避免每次都从失效的 Key 试起
_KEY_STATE = {"idx": 0}


def os_environ_get(name: str) -> str | None:
    import os
    return os.environ.get(name)


def load_quality_config() -> dict[str, Any]:
    import yaml
    if not CONFIG_PATH.exists():
        return {}
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig")) or {}
    return cfg.get("quality", {}) or {}


# --------------------------------------------------------------------------
# 正文提取：只送散文，不送标题/图注/表格/代码
# --------------------------------------------------------------------------

SKIP_LINE_RE = re.compile(
    r"^\s*(#{1,6}\s|!\[|\||<!--|```|>\s*$|-\s*\[)"   # 标题/图片/表格/注释/代码
)
FRONT_MATTER_RE = re.compile(r"^---\s*$")


def extract_prose(manuscript: str) -> tuple[list[dict], str]:
    """
    返回 (段落列表, 拼好的正文)。
    段落结构：{"index": 段落序号, "text": 原文, "offset": 在全文中的起始位置}
    """
    lines = manuscript.splitlines()

    # 跳过 YAML front matter
    start = 0
    if lines and FRONT_MATTER_RE.match(lines[0]):
        for i in range(1, len(lines)):
            if FRONT_MATTER_RE.match(lines[i]):
                start = i + 1
                break

    paragraphs: list[dict] = []
    cursor = 0
    buf: list[str] = []
    buf_start = 0

    def flush():
        nonlocal buf, cursor
        if not buf:
            return
        text = "".join(buf).strip()
        if len(text) >= 20 and not SKIP_LINE_RE.match(text):
            paragraphs.append({"index": len(paragraphs), "text": text, "offset": buf_start})
        buf = []

    for raw in lines[start:]:
        if not raw.strip():
            flush()
            cursor += len(raw) + 1
            continue
        if SKIP_LINE_RE.match(raw):
            flush()
            cursor += len(raw) + 1
            continue
        if not buf:
            buf_start = cursor
        buf.append(raw.strip())
        cursor += len(raw) + 1
    flush()

    return paragraphs, "\n\n".join(p["text"] for p in paragraphs)


def chunk_paragraphs(paragraphs: list[dict], max_chars: int) -> list[list[dict]]:
    """按段落边界切块，避免把一句话劈开。"""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for p in paragraphs:
        n = len(p["text"])
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------
# 调用
# --------------------------------------------------------------------------

def call_api(text: str, is_merge: bool = False, timeout: int = 120,
             retries: int = 2) -> dict[str, Any]:
    """调用朱雀。多 Key 轮换：主 Key 失效(401/403)、限流(429)或报错时自动切备用 Key。"""
    keys = get_keys()
    if not keys:
        get_key()  # 抛出统一的「没有 API Key」提示
    payload = {"text": text, "is_merge": is_merge}
    errors: list[str] = []

    start = _KEY_STATE["idx"] % len(keys)
    order = keys[start:] + keys[:start]

    for key in order:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        for attempt in range(retries + 1):
            try:
                resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)
            except requests.RequestException as e:
                errors.append(f"{mask_key(key)} 网络错误")
                time.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code in (401, 403):
                errors.append(f"{mask_key(key)} 无效({resp.status_code})")
                break                      # 换下一个 Key
            if resp.status_code == 429:
                errors.append(f"{mask_key(key)} 限流(429)")
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                errors.append(f"{mask_key(key)} HTTP{resp.status_code}")
                break                      # 换下一个 Key

            try:
                data = resp.json()
            except ValueError:
                raise ZhuqueError(f"朱雀返回非 JSON：{resp.text[:300]}")
            _KEY_STATE["idx"] = keys.index(key)   # 记住能用的 Key
            return data

    raise ZhuqueError("朱雀调用失败（所有 Key 均不可用）：" + "；".join(errors[-5:]))


def probe_key(key: str, text: str, is_merge: bool = True, timeout: int = 60) -> dict[str, Any]:
    """用指定单个 Key 探活，不参与轮换。"""
    resp = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"text": text, "is_merge": is_merge}, timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise ZhuqueError(f"无效({resp.status_code})")
    if resp.status_code == 429:
        raise ZhuqueError("限流(429)")
    if resp.status_code >= 400:
        raise ZhuqueError(f"HTTP{resp.status_code}")
    try:
        return resp.json()
    except ValueError:
        raise ZhuqueError("返回非 JSON")


# --------------------------------------------------------------------------
# 结果解析
# --------------------------------------------------------------------------

def _ratio(raw: dict) -> dict[str, float]:
    lr = raw.get("labels_ratio") or {}
    out: dict[str, float] = {}
    for k, v in lr.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def ai_rate_of(raw: dict) -> float:
    """
    AI 率（0~1）= labels_ratio["1"]，即被判定为 AI 的字符占全部字符的比例。
    注意 softmax_confidence 是"获胜类别的置信度"，不是"人类概率"，
    不能拿 1-softmax_confidence 当 AI 率。
    """
    return _ratio(raw).get("1", 0.0)


def detect(manuscript: str, chunk_chars: int = 3000) -> dict[str, Any]:
    paragraphs, _ = extract_prose(manuscript)
    if not paragraphs:
        raise ZhuqueError("稿件里没有可检测的正文段落（是不是还没写正文？）")

    chunks = chunk_paragraphs(paragraphs, chunk_chars)

    segments: list[dict] = []
    total_chars = 0
    billed = 0
    weighted = {"0": 0.0, "1": 0.0, "2": 0.0}
    calls: list[dict] = []

    for ci, chunk in enumerate(chunks):
        text = "\n".join(p["text"] for p in chunk)
        raw = call_api(text, is_merge=False)
        mu = raw.get("makers_models_usage") or {}
        uu = raw.get("usage") or {}
        billed += int(mu.get("total_tokens") or 0) if isinstance(mu, dict) else 0
        calls.append({"chunk": ci, "chars": len(text),
                      "status": raw.get("status"),
                      "usage": uu, "makers_models_usage": mu})

        ratio = _ratio(raw)
        n = len(text)
        total_chars += n
        for k in weighted:
            weighted[k] += ratio.get(k, 0.0) * n

        # 段级结果：position 是 [偏移, 长度]（实测确认，不是 [起点, 终点]）
        for seg in raw.get("segment_labels") or []:
            pos = seg.get("position") or [0, 0]
            offset = int(pos[0]) if len(pos) > 0 else 0
            length = int(pos[1]) if len(pos) > 1 else 0
            seg_text = seg.get("text") or text[offset:offset + length]
            label = seg.get("label")
            segments.append({
                "chunk": ci,
                "offset": offset,
                "length": length,
                "label": label,
                "label_name": LABEL_NAMES.get(label, str(label)),
                "conf": seg.get("conf"),
                "order": seg.get("order"),
                "chars": len(seg_text),
                "text": seg_text,
            })

    ratio_total = {k: (v / total_chars if total_chars else 0.0) for k, v in weighted.items()}
    ai_rate = ratio_total.get("1", 0.0)

    flagged = [s for s in segments if s["label"] == LABEL_AI]
    flagged.sort(key=lambda s: -(s.get("conf") or 0))

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "manuscript_sha256": __import__("hashlib").sha256(
            manuscript.encode("utf-8")).hexdigest(),
        "chars": total_chars,
        "chunks": len(chunks),
        "makers_models_usage": billed,
        "calls": calls,
        "labels_ratio": ratio_total,
        "ai_rate": ai_rate,
        "ai_rate_pct": round(ai_rate * 100, 2),
        "segment_count": len(segments),
        "flagged_count": len(flagged),
        "segments": segments,
        "flagged": flagged,
    }


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------

def render_report(result: dict[str, Any], target: float) -> str:
    ai_pct = result["ai_rate_pct"]
    target_pct = round(target * 100, 1)
    ok = result["ai_rate"] <= target

    lines = [
        "# 朱雀 AIGC 检测报告",
        "",
        f"- 检测时间：{result['checked_at']}",
        f"- 正文字数：{result['chars']}（分 {result['chunks']} 块调用）",
        f"- **AI 率：{ai_pct}%**（目标 ≤ {target_pct}%）　{'✅ 达标' if ok else '❌ 未达标'}",
        "",
        "## 三类占比",
        "",
        "| 类别 | 占比 |",
        "|---|---|",
    ]
    for k, name in (("2", "人工"), ("1", "AI"), ("0", "疑似")):
        lines.append(f"| {name} | {round(result['labels_ratio'].get(k, 0.0) * 100, 2)}% |")

    used = result.get("makers_models_usage") or 0
    if used:
        lines.append(f"\n> 本次消耗 makers_models_usage ≈ {used} token"
                     f"（计费口径约正文字符数的 1.67 倍）")

    lines += ["", f"## 需要改写的片段（{len(result['flagged'])} 段）", ""]
    if not result["flagged"]:
        lines.append("没有 AI 段，无需改写。")
    else:
        lines.append("按置信度降序，优先改前几段；每段给出原文，改完可直接替换。")
        lines.append("")
        for i, seg in enumerate(result["flagged"][:40], 1):
            text = seg["text"].strip().replace("\n", " ")
            if len(text) > 300:
                text = text[:300] + "…"
            lines += [
                f"### 第 {i} 段（置信度 {seg.get('conf')}，{seg['chars']} 字）",
                "",
                f"> {text}",
                "",
            ]
    return "\n".join(lines)


def save(result: dict[str, Any], work: Path, target: float) -> tuple[Path, Path]:
    qdir = work / "quality"
    qdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    js = qdir / f"detect-{stamp}.json"
    md = qdir / f"detect-{stamp}.md"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md.write_text(render_report(result, target), encoding="utf-8")

    (qdir / "latest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (qdir / "latest.md").write_text(render_report(result, target), encoding="utf-8")

    # 历史曲线
    hist_path = qdir / "history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8-sig"))
        except Exception:
            hist = []
    hist.append({"at": result["checked_at"], "ai_rate_pct": result["ai_rate_pct"],
                 "chars": result["chars"]})
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")

    return js, md


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="朱雀 AIGC 检测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="自检 Key 与连通性")
    c.add_argument("--text", default="这是一段用于连通性自检的中文文本，用于确认接口与密钥是否可用。")

    d = sub.add_parser("detect", help="检测稿件")
    d.add_argument("manuscript")
    d.add_argument("--work", help="工作区（用于落盘 quality/）")
    d.add_argument("--target", type=float, default=None, help="AI 率目标，如 0.10")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "check":
            keys = get_keys()
            if not keys:
                get_key()
            results = []
            for k in keys:
                try:
                    raw = probe_key(k, args.text)
                    results.append({"key": mask_key(k), "ok": True,
                                    "ai_rate_pct": round(ai_rate_of(raw) * 100, 2)})
                except (ZhuqueError, requests.RequestException) as e:
                    results.append({"key": mask_key(k), "ok": False, "error": str(e)[:120]})
            print(json.dumps({"keys": len(keys), "results": results},
                             ensure_ascii=False, indent=2))
            return 0 if any(r["ok"] for r in results) else 1

        cfg = load_quality_config().get("zhuque", {}) or {}
        target = args.target if args.target is not None else cfg.get("target_ai_rate", 0.10)
        chunk = int(cfg.get("chunk_chars", 3000))

        ms = Path(args.manuscript)
        if not ms.exists():
            print(f"[错误] 找不到稿件：{ms}", file=sys.stderr)
            return 1

        result = detect(ms.read_text(encoding="utf-8-sig"), chunk_chars=chunk)
        work = Path(args.work) if args.work else ms.parent
        js, md = save(result, work, target)

        print(f"AI 率：{result['ai_rate_pct']}%（目标 ≤ {round(target*100,1)}%）")
        print(f"需改写片段：{result['flagged_count']} / {result['segment_count']}")
        print(f"报告：{md}")
        print(f"数据：{js}")
        return 0 if result["ai_rate"] <= target else 2

    except ZhuqueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
