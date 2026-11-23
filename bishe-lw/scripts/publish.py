#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish.py — 按规范命名，把论文推到云效仓库「论文/」目录

命名规则（config.naming）：{学号}_{姓名}_{专业}_{题目}
  output/论文.docx          -> 20220001_张三_计算机科学与技术_基于XXX的系统设计与实现.docx
  output/论文.pdf           -> ...pdf
  output/论文_可编辑版.docx -> ..._可编辑版.docx
  output/论文_可编辑版.pdf  -> ..._可编辑版.pdf

红线：学号/姓名/专业/题目 缺任何一个都拒绝推送（config.required_fields）。
     绝不编造缺失字段。

用法：
    python publish.py 010 --work <工作区> --dry-run   # 只看计划，不动仓库
    python publish.py 010 --work <工作区>             # 真正推送
"""

from __future__ import annotations

import argparse
import json
import re
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

# Windows 文件名非法字符 + 控制字符
ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# hbks-lw-skill 的产物 -> 命名后缀
ARTIFACT_SUFFIX = {
    "论文.docx": "",
    "论文.pdf": "",
    "论文_可编辑版.docx": "_可编辑版",
    "论文_可编辑版.pdf": "_可编辑版",
}

# F04：四件套必须齐全
REQUIRED_ARTIFACTS = ["论文.docx", "论文.pdf", "论文_可编辑版.docx", "论文_可编辑版.pdf"]


def _verify_artifact(path: Path, name: str) -> None:
    """校验产物不是空壳：PDF 以 %PDF 开头，DOCX 是 zip（PK 开头），且大小合理。"""
    try:
        size = path.stat().st_size
    except OSError as e:
        raise yx.YunxiaoError(f"产物不可读 {name}：{e}")
    if size < 1024:
        raise yx.YunxiaoError(f"产物过小（{size} 字节），疑似空壳：{name}")
    with open(path, "rb") as f:
        head = f.read(5)
    if name.lower().endswith(".pdf"):
        if head[:4] != b"%PDF":
            raise yx.YunxiaoError(f"不是有效 PDF（文件头 {head!r}）：{name}")
    else:
        if head[:2] != b"PK":
            raise yx.YunxiaoError(f"不是有效 DOCX（应为 zip/PK，实际 {head!r}）：{name}")


def sanitize(text: str, max_len: int = 80) -> str:
    """清掉非法字符与空白，中文题目不需要空格。"""
    s = ILLEGAL_RE.sub("", str(text or ""))
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.strip(". ")
    return s[:max_len]


def build_basename(fields: dict, template: str) -> str:
    parts = [
        sanitize(fields.get("学号")),
        sanitize(fields.get("姓名")),
        sanitize(fields.get("专业")),
        sanitize(fields.get("题目"), max_len=60),
    ]
    parts = [p for p in parts if p]
    if len(parts) < 4:
        raise yx.YunxiaoError(
            "命名所需字段不全，拒绝生成文件名。缺失："
            + "、".join(k for k in ("学号", "姓名", "专业", "题目") if not fields.get(k))
        )
    return template.format(
        学号=parts[0], 姓名=parts[1], 专业=parts[2], 题目=parts[3]
    ) if "{" in template else "_".join(parts)


def find_artifacts(work: Path) -> dict[str, Path]:
    """在工作区 output/ 里找论文产物（也兼容放在工作区根目录的情况）。"""
    found: dict[str, Path] = {}
    for base in (work / "output", work):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if p.is_file() and p.name in ARTIFACT_SUFFIX and p.name not in found:
                found[p.name] = p
    return found


def plan(repo_query: str, work: Path, template: str, branch: str | None = None) -> dict:
    cfg = yx.load_config()
    repo = yx.resolve_repo(cfg, repo_query)
    branch = branch or yx.default_branch(cfg, repo["id"])
    repo_dir = Path(cfg["paths"]["runs_root"]) / repo["path"]
    out_dir = repo_dir / cfg["paths"]["output_dir"]

    student_json = work / "student.json"
    if not student_json.exists():
        raise yx.YunxiaoError(f"找不到 {student_json}，请先跑 parse_materials.py")
    student = json.loads(student_json.read_text(encoding="utf-8-sig"))
    fields = student.get("fields", {})

    required = cfg.get("required_fields") or ["学号", "姓名", "专业", "题目"]
    missing = [k for k in required if not fields.get(k)]
    if missing:
        raise yx.YunxiaoError(
            "上传前检查未通过，以下字段为空："
            + "、".join(missing)
            + "\n这些字段无法从材料里自动获取，请人工补齐后重试（绝不自动编造）。"
        )

    base = build_basename(fields, template)
    artifacts = find_artifacts(work)

    # F04：四件套必须齐全，且文件头有效、非空
    missing = [n for n in REQUIRED_ARTIFACTS if n not in artifacts]
    if missing:
        raise yx.YunxiaoError(
            "四件套不完整，缺少：" + "、".join(missing)
            + f"\n请在 {work / 'output'} 下补齐后再发布。"
        )
    for name in REQUIRED_ARTIFACTS:
        _verify_artifact(artifacts[name], name)

    moves = []
    for name in REQUIRED_ARTIFACTS:
        src = artifacts[name]
        suffix = ARTIFACT_SUFFIX[name]
        moves.append({
            "from": str(src),
            "to": str(out_dir / f"{base}{suffix}{Path(name).suffix}"),
            "size": src.stat().st_size,
        })

    return {
        "repo": repo["path"],
        "repo_id": repo["id"],
        "branch": branch,
        "repo_dir": str(repo_dir),
        "output_dir": str(out_dir),
        "basename": base,
        "files": moves,
        "student": student,
    }


def apply(plan_data: dict, dry_run: bool, message: str | None = None) -> dict:
    out_dir = Path(plan_data["output_dir"])
    base = plan_data["basename"]
    targets = [Path(mv["to"]) for mv in plan_data["files"]]

    # F02：预演只算计划，绝不建目录/删文件/复制
    if dry_run:
        return {
            "repo": plan_data["repo"], "branch": plan_data["branch"],
            "output_dir": str(out_dir), "basename": base,
            "files": [{"name": Path(mv["to"]).name, "from": mv["from"],
                       "size": mv.get("size")} for mv in plan_data["files"]],
            "pushed": False, "dry_run": True,
            "note": "预演：未创建目录、未删除、未复制、未提交",
        }

    out_dir.mkdir(parents=True, exist_ok=True)

    # F02：只精确替换本次的 4 个目标文件（不用前缀通配删除），并先写 .tmp 再原子替换
    import os as _os
    replaced, tmps = [], []
    try:
        for mv in plan_data["files"]:
            src, dst = Path(mv["from"]), Path(mv["to"])
            tmp = dst.with_name(dst.name + ".tmp")
            shutil.copy2(src, tmp)
            tmps.append(tmp)
        # 全部复制成功后才替换，失败则清理 tmp，原文件不受影响
        for tmp, dst in zip(tmps, targets):
            _os.replace(tmp, dst)
            replaced.append({"name": dst.name, "size": dst.stat().st_size})
        tmps = []
    finally:
        for tmp in tmps:
            try:
                tmp.unlink()
            except OSError:
                pass

    result = {
        "repo": plan_data["repo"],
        "branch": plan_data["branch"],
        "output_dir": str(out_dir),
        "files": replaced,
        "pushed": False,
        "dry_run": False,
    }

    cfg = yx.load_config()
    commit_msg = message or f"docs(论文): 上传 {base}"
    rel_paths = [str(Path(mv["to"]).relative_to(plan_data["repo_dir"]))
                 for mv in plan_data["files"]]
    repo_dir = Path(plan_data["repo_dir"])
    branch = plan_data["branch"]

    original_branch = None
    p = yx._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    if p.returncode == 0:
        original_branch = p.stdout.strip()

    # F05：切分支不再用 checkout -B（那会把目标分支重置到当前 HEAD）
    switched = False
    if branch != original_branch:
        has_local = yx._run_git(["rev-parse", "--verify", "--quiet",
                                 f"refs/heads/{branch}"], cwd=repo_dir).returncode == 0
        if has_local:
            chk = yx._run_git(["checkout", "--quiet", branch], cwd=repo_dir)
        else:
            yx._run_git([*yx._auth_args(cfg), "fetch", "--quiet", "origin", branch], cwd=repo_dir)
            chk = yx._run_git(["checkout", "--quiet", "-b", branch,
                               f"origin/{branch}"], cwd=repo_dir)
        if chk.returncode != 0:
            raise yx.YunxiaoError(f"切换到分支 {branch} 失败：{yx._redact(chk.stderr or '')[:300]}")
        switched = True

    try:
        push = yx.git_push(cfg, repo_dir, plan_data["repo"],
                           branch, commit_msg, dry_run=False, paths=rel_paths)
    finally:
        if switched and original_branch:
            yx._run_git(["checkout", "--quiet", original_branch], cwd=repo_dir)

    result.update(push)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="按规范命名并推送论文到云效仓库")
    ap.add_argument("repo", help="代码库号")
    ap.add_argument("--work", required=True, help="写作工作区（含 student.json 与 output/）")
    ap.add_argument("--dry-run", action="store_true", help="只复制并列出计划，不 commit 不 push")
    ap.add_argument("--branch", help="推送目标分支（默认仓库默认分支）")
    ap.add_argument("--message", help="提交信息")
    args = ap.parse_args(argv)

    try:
        cfg = yx.load_config()
        work = Path(args.work).resolve()
        naming = cfg.get("naming") or "{学号}_{姓名}_{专业}_{题目}"
        p = plan(args.repo, work, naming, branch=args.branch)
        result = apply(p, args.dry_run, args.message)
    except yx.YunxiaoError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
