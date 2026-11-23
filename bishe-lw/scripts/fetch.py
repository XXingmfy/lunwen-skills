#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch.py — 按「代码库号」把仓库拉到本地固定目录

【硬规定】本地落盘位置只能是：<config.paths.runs_root>\\<代码库号>\\
默认 runs_root = D:\\Tools_Home\\DeepseekHarness_Load\\lw

用法：
    python fetch.py 010                 # 拉 bishe010
    python fetch.py bishe010 --refresh  # 删掉重拉
    python fetch.py 010 --json          # 输出机器可读结果
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yx  # noqa: E402


def local_dir(cfg: dict, repo: dict) -> Path:
    """本地落盘目录：<runs_root>/<代码库号>"""
    return Path(cfg["paths"]["runs_root"]) / repo["path"]


def ensure_work_dir(dest: Path) -> Path:
    """
    写作工作区放在克隆目录下的 .work/，并通过 .git/info/exclude 排除，
    保证 manuscript.md / figs/ 这些中间产物永远不会被推到云效。
    """
    work = dest / ".work"
    work.mkdir(parents=True, exist_ok=True)

    exclude = dest / ".git" / "info" / "exclude"
    try:
        text = exclude.read_text(encoding="utf-8-sig") if exclude.exists() else ""
        if ".work/" not in text:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            if text and not text.endswith("\n"):
                text += "\n"
            exclude.write_text(text + ".work/\n", encoding="utf-8")
    except OSError:
        pass
    return work


def work_real_chars(dest: Path) -> int:
    """粗略统计工作区稿件里真正写了多少中文（剔除 front matter 与注释）。"""
    import re
    ms = dest / ".work" / "manuscript.md"
    if not ms.exists():
        return 0
    try:
        t = ms.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return 0
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"^---.*?^---", "", t, flags=re.S | re.M)
    return len(re.findall(r"[\u4e00-\u9fa5]", t))


def fetch(query: str, refresh: bool = False, depth: int | None = 1,
          allow_work_loss: bool = False) -> dict:
    cfg = yx.load_config()
    repo = yx.resolve_repo(cfg, query)
    branch = yx.default_branch(cfg, repo["id"])
    dest = local_dir(cfg, repo)
    refresh_backup = None

    # F01：--refresh 不再删除目录，改为改名备份；有正文时拒绝
    if refresh and dest.exists():
        n = work_real_chars(dest)
        if n >= 200 and not allow_work_loss:
            raise yx.YunxiaoError(
                f"{dest} 里已有约 {n} 个中文字的正文，拒绝 --refresh 删除。\n"
                "请先自行备份 .work（或确认后用 allow_work_loss=True）"
            )
        import datetime as _dt
        bak = dest.with_name(dest.name + f".old-{_dt.datetime.now():%Y%m%d-%H%M%S}")
        dest.rename(bak)
        refresh_backup = str(bak)

    existed = dest.exists()
    if existed:
        if not (dest / ".git").exists():
            raise yx.YunxiaoError(f"{dest} 已存在但不是 git 仓库，请加 --refresh 重建")
        # F01：只检查「已跟踪文件」是否被本地改动，避免 reset --hard 冲掉
        st = yx._run_git(["-c", "core.quotepath=false", "status", "--porcelain", "-uno"], cwd=dest)
        dirty = [l for l in (st.stdout or "").splitlines() if l.strip()]
        if dirty:
            raise yx.YunxiaoError(
                "本地仓库有未提交的已跟踪改动，拒绝 reset --hard 覆盖：\n  "
                + "\n  ".join(dirty[:10])
                + "\n请先提交或还原后再 init。"
            )
        p = yx._run_git([*yx._auth_args(cfg), "fetch", "--quiet", "origin", branch], cwd=dest)
        if p.returncode != 0:
            raise yx.YunxiaoError(f"git fetch 失败：{yx._redact((p.stderr or ''))[:300]}")
        yx._run_git(["checkout", "--quiet", branch], cwd=dest)
        yx._run_git(["reset", "--hard", "--quiet", f"origin/{branch}"], cwd=dest)
        action = "updated"
    else:
        yx.git_clone(cfg, repo, dest, depth=depth)
        action = "cloned"

    # 目录校验
    materials = dest / cfg["paths"]["materials_dir"]
    source = dest / cfg["paths"]["source_dir"]
    output = dest / cfg["paths"]["output_dir"]
    work = ensure_work_dir(dest)

    problems: list[str] = []
    if not materials.is_dir():
        problems.append(f"缺少「{cfg['paths']['materials_dir']}」目录")
    if not source.is_dir():
        problems.append(f"缺少「{cfg['paths']['source_dir']}」目录")
    output.mkdir(parents=True, exist_ok=True)

    materials_files: list[str] = []
    if materials.is_dir():
        materials_files = sorted(p.name for p in materials.iterdir()
                                 if p.is_file() and not p.name.startswith("."))
        if not materials_files:
            problems.append(f"「{materials.name}」目录是空的")

    # 任务书/开题报告是写作依据，只有 PPT 不足以开工
    has_docx = any(f.lower().endswith(".docx") for f in materials_files)
    if materials_files and not has_docx:
        problems.append(
            "开题材料里没有 .docx（任务书/开题报告），只有 PPT 不能作为写作依据，请先补齐材料"
        )

    return {
        "repo": repo["path"],
        "name": repo["name"],
        "id": repo["id"],
        "default_branch": branch,
        "local_dir": str(dest),
        "work_dir": str(work),
        "action": action,
        "refresh_backup": refresh_backup,
        "materials": materials_files,
        "source_dir": str(source) if source.is_dir() else None,
        "output_dir": str(output),
        "problems": problems,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="按代码库号把云效仓库拉到本地固定目录")
    ap.add_argument("repo", help="代码库号，如 010 / bishe010 / 010-基于RAG…")
    ap.add_argument("--refresh", action="store_true", help="备份现有目录后重新克隆")
    ap.add_argument("--force-refresh", action="store_true", help="即使工作区有正文也强行刷新（慎重）")
    ap.add_argument("--full", action="store_true", help="完整克隆（默认浅克隆 depth=1）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        info = fetch(args.repo, refresh=args.refresh, depth=None if args.full else 1,
                     allow_work_loss=args.force_refresh)
    except yx.YunxiaoError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"仓库      : {info['repo']}  ({info['name']})")
        print(f"默认分支  : {info['default_branch']}")
        print(f"本地目录  : {info['local_dir']}  [{info['action']}]")
        if info.get("refresh_backup"):
            print(f"旧目录备份: {info['refresh_backup']}")
        print(f"开题材料  : {', '.join(info['materials']) or '(空)'}")
        print(f"源码目录  : {info['source_dir'] or '(缺失)'}")
        print(f"产出目录  : {info['output_dir']}")
        if info["problems"]:
            print("\n[阻断问题]")
            for p in info["problems"]:
                print(f"  - {p}")
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
