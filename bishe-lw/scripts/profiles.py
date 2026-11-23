#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
profiles.py — 学校论文格式档案库管理

背景：论文排版格式不再是代码，而是 format-profile.json。
本模块负责"这所学校该用哪份档案"以及"怎么把学校模板变成档案"。

档案解析优先级（init 时按序）：
  1. --profile 显式指定
  2. config.schools[学校].profile 指向的档案（本技能 profiles/ 下）
  3. profiles/<学校>.json 同名文件
  4. 仓库里自动发现的学校模板 .docx → 现场逆向 → 入库
  5. config.engine.baseline_profile（内置基线）—— 按 on_missing_profile 决定阻断还是告警

用法：
    python profiles.py list
    python profiles.py check 河北科技师范学院
    python profiles.py extract --school "河北工程技术学院" --template "模板.docx"
    python profiles.py spec    --school "某某大学" --spec "格式规范.md"
    python profiles.py show 河北科技师范学院
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.yaml"


class ProfileError(RuntimeError):
    pass


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise ProfileError(f"找不到配置文件：{CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig")) or {}


def engine_cfg(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    return cfg.get("engine") or {}


def ty_scripts_dir(cfg: dict[str, Any] | None = None) -> Path:
    d = Path(engine_cfg(cfg).get("ty_skill_dir", ""))
    return d / "scripts"


def profiles_dir(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(engine_cfg(cfg).get("profiles_dir") or (SKILL_DIR / "profiles"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_name(school: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "", school or "").strip()
    return s or "未命名学校"


def profile_path(school: str, cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    entry = (cfg.get("schools") or {}).get(school) or {}
    fname = entry.get("profile")
    if fname:
        p = profiles_dir(cfg) / fname
        if p.exists():
            return p
    return profiles_dir(cfg) / f"{safe_name(school)}.json"


# --------------------------------------------------------------------------
# 调用 ty-lw-skill 脚本
# --------------------------------------------------------------------------

def run_ty(name: str, args: list[str], cfg: dict[str, Any] | None = None,
           timeout: int = 300) -> tuple[int, str, str, dict | None]:
    script = ty_scripts_dir(cfg) / name
    if not script.exists():
        raise ProfileError(f"找不到 ty-lw-skill 脚本：{script}")
    p = subprocess.run([sys.executable, str(script), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    summary = None
    for line in reversed((p.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                summary = json.loads(line)
                break
            except ValueError:
                continue
    return p.returncode, p.stdout or "", p.stderr or "", summary


def lint(profile: str | Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    rc, out, err, summary = run_ty("profile_lint.py", [str(profile)], cfg)
    if summary is None:
        return {"ok": rc == 0, "errors": [err.strip()[:500]] if err.strip() else [],
                "warnings": [], "raw": out[-1500:]}
    return summary


# --------------------------------------------------------------------------
# 档案发现
# --------------------------------------------------------------------------

TEMPLATE_HINTS = ("模板", "格式", "规范", "template", "format")
SPEC_SUFFIXES = (".md", ".txt")


def discover_template(repo_dir: Path, cfg: dict[str, Any]) -> Path | None:
    """
    在仓库里找学校论文模板。只认文件名带「模板/格式/规范」的 .docx，
    且优先 开题材料/ 与 论文/ 目录，避免把任务书当模板。
    """
    if not repo_dir or not repo_dir.is_dir():
        return None
    dirs = []
    for key in ("materials_dir", "output_dir"):
        d = repo_dir / (cfg.get("paths") or {}).get(key, "")
        if d.is_dir():
            dirs.append(d)
    dirs.append(repo_dir)

    for d in dirs:
        for p in sorted(d.glob("*.docx")):
            if p.name.startswith("~$"):
                continue
            low = p.stem.lower()
            if any(h in low for h in TEMPLATE_HINTS):
                # 任务书/开题报告名字里也可能含"格式"？加一道排除
                if any(x in p.name for x in ("任务书", "开题报告", "外文翻译")):
                    continue
                return p
    return None


def discover_spec(repo_dir: Path) -> Path | None:
    if not repo_dir or not repo_dir.is_dir():
        return None
    for p in sorted(repo_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in SPEC_SUFFIXES:
            if any(h in p.stem for h in TEMPLATE_HINTS):
                return p
    return None


def resolve(school: str, explicit: str | None = None,
            repo_dir: str | Path | None = None,
            auto_extract: bool = True,
            allow_baseline: bool = False,
            cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    返回 {"path", "source", "warnings", "need_template"}。
    source ∈ explicit / library / auto_extracted / baseline。
    allow_baseline=True 时，缺档案也回退基线（对应 init --allow-baseline）。
    """
    cfg = cfg or load_config()
    eng = engine_cfg(cfg)
    warnings: list[str] = []

    # 1) 显式指定
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise ProfileError(f"--profile 指定的档案不存在：{p}")
        return {"path": str(p), "source": "explicit", "warnings": warnings}

    # 2) 档案库
    p = profile_path(school, cfg)
    if p.exists():
        return {"path": str(p), "source": "library", "warnings": warnings}

    # 3) 仓库里自动发现模板 → 现场逆向
    if auto_extract and repo_dir:
        tpl = discover_template(Path(repo_dir), cfg)
        if tpl:
            out = profile_path(school, cfg)
            try:
                rc, so, se, summary = _extract(school, tpl, out, cfg)
                if rc == 0:
                    warnings.append(f"已从仓库内模板自动逆向生成档案：{tpl.name} → {out}")
                    return {"path": str(out), "source": "auto_extracted",
                            "warnings": warnings}
                warnings.append(f"自动逆向失败（{tpl.name}）：{(se or so)[:200]}")
            except ProfileError as e:
                warnings.append(f"自动逆向失败：{e}")

    # 4) 基线
    baseline = Path(eng.get("baseline_profile") or
                    Path(eng.get("ty_skill_dir", "")) / "assets" / "profiles" / "hbks-baseline.json")
    mode = (eng.get("on_missing_profile") or "block").lower()
    if mode == "baseline" or allow_baseline:
        warnings.append(
            f"「{school}」没有格式档案，已回退到内置基线（河北科技师范学院）。"
            "排版可能与该校要求不一致，交付前必须人工核对！"
        )
        if not baseline.exists():
            raise ProfileError(f"基线档案也不存在：{baseline}")
        return {"path": str(baseline), "source": "baseline", "warnings": warnings,
                "need_template": True}

    raise ProfileError(
        f"「{school}」还没有论文格式档案，无法按该校规范排版。\n"
        "请提供该校的论文模板 .docx（最好含封面与样式），然后执行：\n"
        f'  python profiles.py extract --school "{school}" --template "模板.docx"\n'
        "如果只有文字版格式规范（通知/PDF 转文字），用：\n"
        f'  python profiles.py spec --school "{school}" --spec "规范.md"\n'
        "确认要先用内置基线凑合（排版可能与学校要求不符）：init 时加 --allow-baseline"
    )


def _extract(school: str, template: Path, out: Path, cfg: dict[str, Any]) -> tuple[int, str, str, dict | None]:
    out.parent.mkdir(parents=True, exist_ok=True)
    report = out.with_suffix(".report.md")
    return run_ty("extract_template.py",
                  [str(template), "--out", str(out), "--school", school,
                   "--report", str(report)], cfg)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def check_school_match(profile_file: str | Path, school: str) -> list[str]:
    """档案里的校名和实际学校不一致 → 是致命错误（会生成错抬头的封面）。"""
    try:
        d = json.loads(Path(profile_file).read_text(encoding="utf-8-sig"))
    except Exception as e:
        return [f"档案无法读取：{e}"]
    ps = (d.get("school") or "").strip()
    if ps and school and ps != school:
        return [f"档案校名「{ps}」与实际学校「{school}」不一致，拒绝使用（会生成错误封面）"]
    return []


def summarize(profile_file: str | Path) -> dict[str, Any]:
    d = json.loads(Path(profile_file).read_text(encoding="utf-8-sig"))
    wb = d.get("word_budget") or {}
    return {
        "school": d.get("school"),
        "doc_type": d.get("doc_type"),
        "word_budget": wb,
        "source_type": (d.get("source") or {}).get("type"),
        "source_paths": (d.get("source") or {}).get("paths"),
        "extracted_at": (d.get("source") or {}).get("extracted_at"),
        "sections": [s.get("key") for s in (d.get("sections") or [])],
        "quirks_count": len(d.get("quirks") or []),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="学校论文格式档案库")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出档案库")

    c = sub.add_parser("check", help="体检指定档案")
    c.add_argument("target", help="学校名或档案路径")

    s = sub.add_parser("show", help="查看档案摘要")
    s.add_argument("school")

    e = sub.add_parser("extract", help="从学校模板 docx 逆向生成档案")
    e.add_argument("--school", required=True)
    e.add_argument("--template", required=True)
    e.add_argument("--force", action="store_true", help="覆盖已存在的档案")

    sp = sub.add_parser("spec", help="从文字规范解析档案")
    sp.add_argument("--school", required=True)
    sp.add_argument("--spec", required=True)
    sp.add_argument("--base", help="以已有档案为底，只覆盖规范明确写到的字段")
    sp.add_argument("--force", action="store_true")

    args = ap.parse_args(argv)

    try:
        cfg = load_config()

        if args.cmd == "list":
            d = profiles_dir(cfg)
            rows = []
            for p in sorted(d.glob("*.json")):
                try:
                    rows.append({"file": p.name, **summarize(p)})
                except Exception as e:
                    rows.append({"file": p.name, "error": str(e)})
            print(json.dumps({"profiles_dir": str(d), "count": len(rows), "profiles": rows},
                             ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "show":
            p = profile_path(args.school, cfg)
            if not p.exists():
                print(f"[错误] 没有「{args.school}」的档案：{p}", file=sys.stderr)
                return 1
            print(json.dumps(summarize(p), ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "check":
            p = Path(args.target) if Path(args.target).exists() else profile_path(args.target, cfg)
            if not p.exists():
                print(f"[错误] 找不到档案：{args.target}", file=sys.stderr)
                return 1
            res = lint(p, cfg)
            print(f"档案：{p}")
            print(f"ERROR {len(res.get('errors') or [])} ｜ WARN {len(res.get('warnings') or [])}")
            for x in (res.get("errors") or []):
                print(f"  [ERROR] {x}")
            for x in (res.get("warnings") or []):
                print(f"  [WARN ] {x}")
            return 0 if res.get("ok") else 1

        if args.cmd == "extract":
            tpl = Path(args.template)
            if not tpl.exists():
                print(f"[错误] 模板不存在：{tpl}", file=sys.stderr)
                return 1
            out = profile_path(args.school, cfg)
            if out.exists() and not args.force:
                print(f"[错误] 档案已存在：{out}\n重跑加 --force 覆盖", file=sys.stderr)
                return 1
            rc, so, se, summary = _extract(args.school, tpl, out, cfg)
            print(so[-3000:] if so else "")
            if se.strip():
                print(se[-1000:], file=sys.stderr)
            if rc != 0:
                return rc
            res = lint(out, cfg)
            print(f"\n档案已写入：{out}")
            print(f"体检：ERROR {len(res.get('errors') or [])} ｜ WARN {len(res.get('warnings') or [])}")
            for x in (res.get("errors") or []):
                print(f"  [ERROR] {x}")
            return 0 if res.get("ok") else 1

        if args.cmd == "spec":
            spec = Path(args.spec)
            if not spec.exists():
                print(f"[错误] 规范文件不存在：{spec}", file=sys.stderr)
                return 1
            out = profile_path(args.school, cfg)
            if out.exists() and not args.force:
                print(f"[错误] 档案已存在：{out}\n重跑加 --force 覆盖", file=sys.stderr)
                return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            a = [str(spec), "--out", str(out), "--school", args.school]
            if args.base:
                a += ["--base", args.base]
            rc, so, se, summary = run_ty("parse_spec.py", a, cfg)
            print(so[-3000:] if so else "")
            if se.strip():
                print(se[-1000:], file=sys.stderr)
            if rc != 0:
                return rc
            res = lint(out, cfg)
            print(f"\n档案已写入：{out}")
            print(f"体检：ERROR {len(res.get('errors') or [])} ｜ WARN {len(res.get('warnings') or [])}")
            return 0 if res.get("ok") else 1

    except ProfileError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("[错误] 调用 ty-lw-skill 脚本超时", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
