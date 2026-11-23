#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yx.py — 云效（Codeup / Projex）客户端

只做三件事：读配置、调 OpenAPI、跑 git。
令牌永远不打印、不写进仓库、不落到 .git/config。

用法（也可作为模块 import）：
    python yx.py repos                      # 列出全部仓库
    python yx.py resolve 010                # 解析"仓库号"
    python yx.py tree bishe010 开题材料      # 看目录
    python yx.py check                      # 自检：配置+令牌+连通性
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import requests
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.yaml"
SECRETS_PATH = SKILL_DIR / "secrets.env"

API_PREFIX = "/oapi/v1"


class YunxiaoError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 配置与凭据
# --------------------------------------------------------------------------

def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        raise YunxiaoError(f"找不到配置文件：{p}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_secrets_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if not SECRETS_PATH.exists():
        return out
    for raw in SECRETS_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_pat(required: bool = True) -> str | None:
    """令牌优先级：环境变量 > secrets.env。"""
    pat = os.environ.get("YUNXIAO_PAT")
    if not pat:
        pat = _read_secrets_file().get("YUNXIAO_PAT")
    if required and not pat:
        raise YunxiaoError(
            "没有找到云效令牌。请任选其一：\n"
            f"  1) 在 {SECRETS_PATH} 写入一行： YUNXIAO_PAT=pt-xxxx\n"
            "  2) 设置环境变量 YUNXIAO_PAT"
        )
    return pat


def get_git_user(cfg: dict[str, Any]) -> str:
    return os.environ.get("YUNXIAO_USER") or cfg["yunxiao"]["user"]


def _base_url(cfg: dict[str, Any]) -> str:
    dom = cfg["yunxiao"]["domain"].rstrip("/")
    if dom.startswith("http"):
        return dom
    return f"https://{dom}"


# --------------------------------------------------------------------------
# OpenAPI
# --------------------------------------------------------------------------

def api(cfg: dict[str, Any], path: str, method: str = "GET",
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: int = 40) -> Any:
    url = _base_url(cfg) + API_PREFIX + path
    headers = {
        "x-yunxiao-token": get_pat(),
        "Content-Type": "application/json",
    }
    try:
        resp = requests.request(method, url, headers=headers, params=params,
                                json=body, timeout=timeout)
    except requests.RequestException as e:
        raise YunxiaoError(f"请求失败：{method} {path} -> {e}") from e

    if resp.status_code == 401:
        raise YunxiaoError(
            "令牌无效或已过期（HTTP 401）。请到 云效工作台 → 个人设置 → 个人访问令牌 重新生成。"
        )
    if resp.status_code == 403:
        detail = ""
        try:
            detail = resp.json().get("errorMessage", "")
        except Exception:
            pass
        raise YunxiaoError(
            f"令牌没有该接口的权限（HTTP 403）{('：' + detail) if detail else ''}\n"
            "请在令牌权限里勾选「代码管理 Codeup 读写」与「项目协作 Projex 只读」。"
        )
    if resp.status_code == 404:
        raise YunxiaoError(f"接口不存在或资源找不到（HTTP 404）：{path}")
    if resp.status_code >= 400:
        raise YunxiaoError(f"云效接口报错 HTTP {resp.status_code}：{resp.text[:300]}")
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def list_repos(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """列出全部代码库（自动翻页）。"""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        chunk = api(cfg, "/codeup/repositories", params={"page": page, "perPage": 100})
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return out


def repo_branches(cfg: dict[str, Any], repo_id: int | str) -> list[dict[str, Any]]:
    return api(cfg, f"/codeup/repositories/{repo_id}/branches") or []


def default_branch(cfg: dict[str, Any], repo_id: int | str) -> str:
    """默认分支因仓库而异（有 master 也有 main），必须实时探测。
    OpenAPI 不可用时退回 git ls-remote --symref。"""
    try:
        for b in repo_branches(cfg, repo_id):
            if b.get("defaultBranch"):
                return b["name"]
        branches = repo_branches(cfg, repo_id)
        if branches:
            return branches[0]["name"]
        raise YunxiaoError(f"仓库 {repo_id} 没有任何分支（可能是空仓库）")
    except YunxiaoError:
        path = _REPO_PATH_BY_ID.get(str(repo_id))
        if path:
            hit = _git_probe_repo(cfg, path)
            if hit:
                return hit["defaultBranch"]
        raise


# --------------------------------------------------------------------------
# OpenAPI 不可用时的 git 兜底（令牌已经失效、但 git over HTTPS 仍可用时）
# 只用来解析仓库路径和默认分支，不改任何写操作
# --------------------------------------------------------------------------

_REPO_PATH_BY_ID: dict[str, str] = {}
_PROBE_CACHE: dict[str, dict[str, Any] | None] = {}


def _git_probe_repo(cfg: dict[str, Any], repo_path: str) -> dict[str, Any] | None:
    """用 git ls-remote 探测仓库是否存在，并读默认分支（不依赖 OpenAPI）。"""
    key = repo_path.lower()
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    url = clean_url(cfg, repo_path)
    p = _run_git([*_auth_args(cfg), "ls-remote", "--symref", url, "HEAD"])
    branch = ""
    if p.returncode == 0:
        for line in (p.stdout or "").splitlines():
            if line.startswith("ref:") and line.rstrip().endswith("HEAD"):
                branch = line.split("refs/heads/", 1)[-1].split("\t")[0].strip()
                break
    if not branch:
        _PROBE_CACHE[key] = None
        return None
    info = {"id": repo_path, "path": repo_path, "name": repo_path.rsplit("/", 1)[-1],
            "defaultBranch": branch, "webUrl": url[:-4]}
    _PROBE_CACHE[key] = info
    _REPO_PATH_BY_ID[str(repo_path)] = repo_path
    _REPO_PATH_BY_ID[info["name"]] = repo_path
    return info


def _resolve_by_git(cfg: dict[str, Any], q: str) -> dict[str, Any] | None:
    """005 / bishe005 / your_namespace/bishe005 → 仓库对象：按候选名字逐个探远端。"""
    ns = str(cfg["yunxiao"].get("namespace") or "").strip("/")
    raw = q.strip().strip("/")
    base = raw.rsplit("/", 1)[-1]
    cands: list[str] = []
    if "/" in raw:
        cands.append(raw)
    if base.lower().startswith("bishe"):
        names = [base]
    elif raw.isdigit():
        names = [f"bishe{raw.zfill(3)}", f"bishe{raw}"]
    else:
        names = [base]
    for name in names:
        if ns:
            cands.append(f"{ns}/{name}")
        cands.append(name)
    for c in dict.fromkeys(cands):
        hit = _git_probe_repo(cfg, c)
        if hit:
            return hit
    return None


def tree(cfg: dict[str, Any], repo_id: int | str, ref: str, path: str = "") -> list[dict[str, Any]]:
    return api(cfg, f"/codeup/repositories/{repo_id}/files/tree",
               params={"refName": ref, "path": path}) or []


# --------------------------------------------------------------------------
# 仓库号解析
# --------------------------------------------------------------------------

def resolve_repo(cfg: dict[str, Any], query: str,
                 repos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    把用户嘴里的"仓库号"解析成仓库对象。支持：
      bishe010 / your_namespace/bishe010 / 010 / 10 / 010-基于RAG… / 仓库ID
    """
    q = (query or "").strip()
    if not q:
        raise YunxiaoError("仓库号不能为空")

    if repos is None:
        try:
            repos = list_repos(cfg)
        except YunxiaoError:
            repos = []
    if not repos:
        hit = _resolve_by_git(cfg, q)
        if hit:
            return hit
        raise YunxiaoError(
            "云效仓库列表不可用（OpenAPI 令牌失效/权限不足），"
            f"git 也探测不到仓库「{q}」。请重建令牌，或确认代码库号。")

    low = q.lower()

    # 1) 仓库 ID
    if q.isdigit():
        for r in repos:
            if str(r["id"]) == q:
                return r

    # 2) path / pathWithNamespace 精确
    for r in repos:
        if low in (str(r.get("path", "")).lower(),
                   str(r.get("pathWithNamespace", "")).lower()):
            return r

    # 3) 名称精确
    for r in repos:
        if low == str(r.get("name", "")).lower():
            return r

    # 4) 纯数字序号：010 / 10 -> bishe010 或 "010-xxx"
    if q.isdigit():
        num = q.lstrip("0") or "0"
        for r in repos:
            path = str(r.get("path", "")).lower()
            name = str(r.get("name", ""))
            m = "".join(ch for ch in path if ch.isdigit()).lstrip("0") or "0"
            if m == num:
                return r
            if name[:len(num)] == num and (len(name) == len(num) or not name[len(num)].isdigit()):
                return r

    # 5) 模糊：path 或 name 包含
    hits = [r for r in repos
            if low in str(r.get("path", "")).lower() or low in str(r.get("name", "")).lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        names = "、".join(f"{h['path']}({h['name']})" for h in hits[:8])
        raise YunxiaoError(f"「{query}」匹配到 {len(hits)} 个仓库，请说得更具体：{names}")

    raise YunxiaoError(f"找不到仓库「{query}」。可用仓库：{', '.join(r['path'] for r in repos[:20])}")


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _auth_args(cfg: dict[str, Any]) -> list[str]:
    """用 http.extraheader 传认证，令牌只存在于进程参数/内存，不写进 .git/config、不进 URL。
    （F07：原实现把 PAT 拼进 remote URL 再恢复，异常退出会残留。）"""
    import base64
    user = get_git_user(cfg)
    pat = get_pat() or ""
    token = base64.b64encode(f"{user}:{pat}".encode("utf-8")).decode("ascii")
    return ["-c", f"http.extraheader=AUTHORIZATION: Basic {token}"]


def _redact(text: str) -> str:
    pat = get_pat() or ""
    out = text or ""
    if pat:
        out = out.replace(pat, "***")
    return out


def clean_url(cfg: dict[str, Any], repo_path: str) -> str:
    host = cfg["yunxiao"]["domain"].rstrip("/")
    return f"https://{host}/codeup/{repo_path}.git"


def _run_git(args: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                       env=_git_env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p


def git_clone(cfg: dict[str, Any], repo: dict[str, Any], dest: str | Path,
              depth: int | None = 1) -> Path:
    """克隆到 dest。远端 URL 从一开始就不含凭据（认证走 extraheader），
    所以 .git/config 天然干净，无需事后抹除。"""
    dest = Path(dest)
    if dest.exists():
        raise YunxiaoError(f"目标目录已存在：{dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    args = [*_auth_args(cfg), "clone", "--quiet"]
    if depth:
        args += ["--depth", str(depth)]
    args += [clean_url(cfg, repo["path"]), str(dest)]

    p = _run_git(args)
    if p.returncode != 0:
        raise YunxiaoError(f"克隆失败 {repo['path']}：{_redact((p.stderr or '').strip())[:300]}")
    return dest


def remote_head(cfg: dict[str, Any], workdir: str | Path, branch: str) -> str | None:
    p = _run_git([*_auth_args(cfg), "ls-remote", "--heads", "origin",
                  f"refs/heads/{branch}"], cwd=workdir)
    if p.returncode != 0:
        return None
    for line in (p.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(f"refs/heads/{branch}"):
            return parts[0]
    return None


def _staged_outside(workdir: Path, paths: list[str]) -> list[str]:
    """返回「已暂存但不属于本次发布范围」的文件（F05：防止把别人的改动一起提交）。"""
    p = _run_git(["-c", "core.quotepath=false", "diff", "--cached", "--name-only"], cwd=workdir)
    if p.returncode != 0:
        return []
    prefixes = [str(x).replace("\\", "/").rstrip("/") + "/" for x in paths] + [str(x) for x in paths]
    outside = []
    for f in (p.stdout or "").splitlines():
        f = f.strip()
        if not f:
            continue
        fn = f.replace("\\", "/")
        if not any(fn == pre or fn.startswith(pre) for pre in prefixes):
            outside.append(f)
    return outside


def git_push(cfg: dict[str, Any], workdir: str | Path, repo_path: str,
             branch: str, message: str, dry_run: bool = False,
             paths: list[str] | None = None,
             allow_outside_staged: bool = False) -> dict[str, Any]:
    """
    在 workdir 里 add + commit + push 到 branch。
    - paths 给定时只提交这些路径
    - 已暂存的「范围外」文件默认阻断（F05）
    - 无文件变化时仍检查是否领先远端并重推（F06）
    - 推送后核验远端 SHA（F06）
    - 认证据不走 URL/config（F07）
    - dry_run 完全不写（不 add、不 commit）
    """
    workdir = Path(workdir)
    if not (workdir / ".git").exists():
        raise YunxiaoError(f"不是 git 仓库：{workdir}")

    add_args = ["add", "--", *paths] if paths else ["add", "-A"]
    status_args = (["-c", "core.quotepath=false", "status", "--porcelain", "--", *paths]
                   if paths else ["-c", "core.quotepath=false", "status", "--porcelain"])

    if dry_run:
        st = _run_git(status_args, cwd=workdir)
        changed = [l for l in (st.stdout or "").splitlines() if l.strip()]
        outside = _staged_outside(workdir, paths) if paths else []
        return {"changed": len(changed), "pushed": False, "dry_run": True,
                "would_commit": changed, "staged_outside": outside}

    # F05：范围外已暂存内容阻断
    if paths and not allow_outside_staged:
        outside = _staged_outside(workdir, paths)
        if outside:
            raise YunxiaoError(
                "暂存区里有本次发布范围外的文件，已阻断提交（防止误提交）：\n  "
                + "\n  ".join(outside[:10])
                + "\n请先 `git restore --staged <文件>` 处理，或确认后用 allow_outside_staged=True。"
            )

    _run_git(add_args, cwd=workdir)
    status = _run_git(status_args, cwd=workdir)
    if status.returncode != 0:
        raise YunxiaoError(f"git status 失败：{_redact(status.stderr)[:300]}")
    changed = [l for l in (status.stdout or "").splitlines() if l.strip()]

    committed = False
    if changed:
        commit = _run_git(
            ["-c", "user.name=毕设论文流水线", "-c", "user.email=pipeline@local",
             "commit", "-m", message], cwd=workdir)
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
            raise YunxiaoError(f"git commit 失败：{_redact(commit.stderr or commit.stdout)[:300]}")
        committed = True

    local = _run_git(["rev-parse", "HEAD"], cwd=workdir).stdout.strip()
    if not local:
        raise YunxiaoError("无法读取本地 HEAD")

    # F06：无改动也要判断是否领先远端
    rsha = remote_head(cfg, workdir, branch)
    if rsha == local:
        return {"changed": len(changed), "pushed": False, "commit": local[:7],
                "branch": branch, "files": changed, "note": "远端已是最新，无需推送"}

    push = _run_git([*_auth_args(cfg), "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=workdir)
    if push.returncode != 0:
        msg = _redact(push.stderr or push.stdout)[:400]
        hint = ("\n远端已有新提交，先 `git fetch origin` → `git rebase origin/%s` 再重试。" % branch
                if "rejected" in msg or "non-fast-forward" in msg else "")
        raise YunxiaoError(f"git push 失败：{msg}{hint}")

    # F06：核验远端确实收到
    rsha2 = remote_head(cfg, workdir, branch)
    if rsha2 != local:
        raise YunxiaoError(f"推送后核验失败：远端 HEAD={rsha2} 与本地 {local} 不一致")

    return {"changed": len(changed), "pushed": True, "committed": committed,
            "commit": local[:7], "branch": branch, "files": changed,
            "remote_verified": True}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    cmd = argv[0]
    cfg = load_config()

    try:
        if cmd == "check":
            pat = get_pat()
            masked = f"{pat[:6]}…{pat[-4:]}" if pat else "(无)"
            repos = list_repos(cfg)
            bishe = [r for r in repos if str(r.get("path", "")).startswith("bishe")]
            _print({
                "domain": cfg["yunxiao"]["domain"],
                "user": get_git_user(cfg),
                "token": masked,
                "仓库总数": len(repos),
                "毕设仓库数": len(bishe),
                "毕设仓库": [r["path"] for r in bishe],
            })
            return 0

        if cmd == "repos":
            repos = list_repos(cfg)
            _print([{"path": r["path"], "name": r["name"], "id": r["id"]} for r in repos])
            return 0

        if cmd == "resolve":
            repo = resolve_repo(cfg, argv[1])
            branch = default_branch(cfg, repo["id"])
            _print({"path": repo["path"], "name": repo["name"], "id": repo["id"],
                    "default_branch": branch, "web": repo.get("webUrl")})
            return 0

        if cmd == "tree":
            repo = resolve_repo(cfg, argv[1])
            branch = argv[3] if len(argv) > 3 else default_branch(cfg, repo["id"])
            path = argv[2] if len(argv) > 2 else ""
            items = tree(cfg, repo["id"], branch, path)
            _print([{"name": i["name"], "type": i["type"], "path": i["path"]} for i in items])
            return 0

        print(f"未知命令：{cmd}", file=sys.stderr)
        print(__doc__)
        return 2

    except YunxiaoError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
