"""复用 bishe-lw 的云效客户端（yx.py）来解析仓库号、读配置、鉴权、克隆/推送。

不复制 yx.py，运行时定位 bishe-lw skill 并 import，保证令牌/域名/命名空间只有一处配置。
"""
from __future__ import annotations

import sys
from pathlib import Path

_YX = None


def _candidate_dirs():
    home = Path.home()
    return [
        home / ".dsh" / "skills" / "bishe-lw" / "scripts",
        home / ".config" / "magpie" / "library" / "skills" / "bishe-lw" / "scripts",
        Path(r"C:/Users/<user>/.dsh/skills/bishe-lw/scripts"),
    ]


def yx():
    global _YX
    if _YX is not None:
        return _YX
    for d in _candidate_dirs():
        if (d / "yx.py").exists():
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            import yx as _m  # noqa: E402

            _YX = _m
            return _m
    raise RuntimeError("找不到 bishe-lw 的 scripts/yx.py（解析云效仓库号/鉴权需要它）")


def load():
    return yx().load_config()


def resolve(query: str):
    """返回 (cfg, repo, branch)。repo 含 id/path/name/webUrl。"""
    m = yx()
    cfg = m.load_config()
    repo = m.resolve_repo(cfg, query)
    try:
        branch = m.default_branch(cfg, repo["id"])
    except Exception:
        branch = repo.get("defaultBranch") or "main"
    return cfg, repo, branch


def clean_url(cfg, repo_path: str) -> str:
    return yx().clean_url(cfg, repo_path)


def auth_args(cfg=None):
    """git 认证参数（http.extraheader，PAT 不落盘）。"""
    m = yx()
    if cfg is None:
        cfg = m.load_config()
    return m._auth_args(cfg)


def clone_or_update(cfg, repo, branch, dest, full: bool = True):
    """克隆或更新到 dest；返回 'cloned' / 'updated'。"""
    m = yx()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").exists():
        p = m._run_git([*m._auth_args(cfg), "fetch", "--quiet", "origin", branch], cwd=dest)
        if p.returncode != 0:
            raise RuntimeError(f"git fetch 失败: {(p.stderr or '')[:300]}")
        m._run_git(["-c", "core.quotepath=false", "checkout", "--quiet", branch], cwd=dest)
        m._run_git(["reset", "--hard", "--quiet", f"origin/{branch}"], cwd=dest)
        return "updated"
    m.git_clone(cfg, repo, dest, depth=None if full else 1)
    return "cloned"


def pat(cfg=None) -> str | None:
    try:
        m = yx()
        return m.get_pat(required=False)
    except Exception:
        return None
