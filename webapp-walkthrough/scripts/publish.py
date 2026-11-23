"""把教学视频上传到云效（Codeup）仓库的指定目录，默认与论文存放同一目录。

用法:
  python -I publish.py <工作目录> [--video <成片路径>] [--dry-run] [--force]

配置在 config.json 的 publish 段：
  "publish": {
    "enabled": true,
    "repo": "https://example-cn-beijing.devops.aliyuncs.com/codeup/bishe007.git",
    "branch": "main",
    "dir": "论文",                       # 与论文同目录
    "subdir": "",                        # 可选：再建子目录
    "filename": "{system}_教学视频_{date}.mp4",
    "includeDocs": false,                # 是否连同 教学讲稿.md / 功能点清单.md 一起上传
    "localRepo": "",                     # 可选：复用已有本地 clone（避免重复 clone）
    "commit": "docs(演示视频): 新增《{system}》教学视频（{date}）"
  }

安全：只 git add 目标目录下的目标文件；不 force push；localRepo 有未推送提交或已跟踪改动时默认中止（--force 可覆盖）。
凭据：复用本机 git 凭据（Git Credential Manager）；若配置 publish.token，则在推送/拉取时临时用 token 认证，不落盘。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run(cmd, cwd=None, env=None, check=False):
    e = dict(os.environ)
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GIT_ASKPASS"] = e.get("GIT_ASKPASS", "echo")
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=e)
    if check and p.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{(p.stdout or '')[-800:]}\n{(p.stderr or '')[-800:]}")
    return p


def _auth_prefix():
    """若能用 bishe-lw 的 PAT，则用 http.extraheader 认证（不写 URL/config）。"""
    try:
        import base64

        import repo as rt

        cfg = rt.load()
        pat = rt.pat(cfg)
        if pat:
            user = (cfg.get("yunxiao") or {}).get("user") or "oauth2"
            tok = base64.b64encode(f"{user}:{pat}".encode("utf-8")).decode("ascii")
            return ["-c", f"http.extraheader=AUTHORIZATION: Basic {tok}"]
    except Exception:
        pass
    return []


def slug_of(url):
    u = url.rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return os.path.basename(u) or "repo"


def autodetect_video(workdir, cfg):
    # 优先 meta 里记录的成片目录，否则搜索候选目录里最新的 mp4
    cands = []
    for d in [cfg.get("outDir"), (cfg.get("projectDir") or "") and os.path.join(cfg.get("projectDir"), "video_demo"), "D:/video_demo"]:
        if d and os.path.isdir(d):
            cands += [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".mp4")]
    if not cands:
        return None
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name or "video.mp4"


def prepare_repo(pub, log):
    repo = pub["repo"]
    branch = pub.get("branch") or "main"
    local = pub.get("localRepo")
    cache = local or os.path.join(os.path.expanduser("~"), "ego-walkthrough", "_publish", slug_of(repo))

    if local:
        if not os.path.isdir(os.path.join(local, ".git")):
            raise RuntimeError(f"localRepo 不是 git 仓库: {local}")
        run(["git", *_auth_prefix(), "fetch", "origin", branch], cwd=local, check=True)
        # 安全性检查：有未推送提交或已跟踪改动则中止
        ahead = run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], cwd=local).stdout.strip()
        porcelain = run(["git", "status", "--porcelain"], cwd=local).stdout
        tracked_dirty = [l for l in porcelain.splitlines() if l.strip() and not l.startswith("??")]
        if ahead not in ("", "0") and "--force" not in sys.argv:
            raise RuntimeError(f"localRepo 有 {ahead} 个未推送提交，已中止（确认后加 --force）")
        if tracked_dirty and "--force" not in sys.argv:
            raise RuntimeError(f"localRepo 有已跟踪改动，已中止（确认后加 --force）：{tracked_dirty[:3]}")
        run(["git", "checkout", branch], cwd=local, check=False)
        run(["git", "reset", "--hard", f"origin/{branch}"], cwd=local, check=True)
        log(f"复用本地仓库 {local} @ {branch}")
        return local
    else:
        if not os.path.isdir(os.path.join(cache, ".git")):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            run(["git", *_auth_prefix(), "clone", "--depth", "1", "-b", branch, repo, cache], check=True)
            log(f"克隆 {repo} -> {cache}")
        else:
            run(["git", *_auth_prefix(), "fetch", "origin", branch], cwd=cache, check=True)
            run(["git", "reset", "--hard", f"origin/{branch}"], cwd=cache, check=True)
            log(f"更新缓存仓库 {cache} @ {branch}")
        return cache


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--video", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    workdir = os.path.abspath(args.workdir)
    cfg = load_json(os.path.join(workdir, "config.json"), {})
    pub = cfg.get("publish") or {}
    def log(m):
        print(f"[publish] {m}", flush=True)

    if not pub.get("enabled") and not args.dry_run:
        print(json.dumps({"ok": True, "skipped": True, "reason": "publish.enabled=false"}, ensure_ascii=False))
        return

    video = args.video
    if video and not os.path.exists(video):
        log(f"--video 路径不存在，改为自动探测: {video}")
        video = None
    video = video or autodetect_video(workdir, cfg)
    if not video or not os.path.exists(video):
        print(json.dumps({"ok": False, "error": "找不到成片 mp4，请用 --video 指定"}, ensure_ascii=False))
        sys.exit(1)

    repo = pub.get("repo")
    if not repo:
        print(json.dumps({"ok": False, "error": "publish.repo 未配置"}, ensure_ascii=False))
        sys.exit(1)
    branch = pub.get("branch") or "main"
    target_dir = (pub.get("dir") or "论文").strip("/")
    subdir = (pub.get("subdir") or "").strip("/")
    include_docs = bool(pub.get("includeDocs"))
    system = cfg.get("systemName") or "system"
    date = datetime.now().strftime("%Y%m%d")
    fname_tpl = pub.get("filename") or "{system}_教学视频_{date}.mp4"
    out_name = sanitize(
        fname_tpl.format(system=system, date=date, ext=os.path.splitext(video)[1].lstrip("."))
    )
    if not out_name.lower().endswith(".mp4"):
        out_name += ".mp4"
    commit_tpl = pub.get("commit") or "docs(演示视频): 新增《{system}》教学视频（{date}）"
    commit_msg = commit_tpl.format(system=system, date=date)

    rel_dir = os.path.join(target_dir, subdir) if subdir else target_dir
    log(f"目标: {repo} #{branch} -> {rel_dir}/{out_name}")
    if args.dry_run:
        print(json.dumps({"ok": True, "dryRun": True, "repo": repo, "branch": branch, "dir": rel_dir, "file": out_name, "video": video}, ensure_ascii=False))
        return

    cache = prepare_repo(pub, log)
    dest_dir = os.path.join(cache, rel_dir)
    os.makedirs(dest_dir, exist_ok=True)

    copied = []
    dest_video = os.path.join(dest_dir, out_name)
    shutil.copyfile(video, dest_video)
    copied.append(os.path.relpath(dest_video, cache))

    if include_docs:
        for src_name, out_suffix in [("教学讲稿.md", "教学讲稿.md"), ("功能点清单.md", "功能点清单.md")]:
            srcp = os.path.join(workdir, "run", src_name)
            if os.path.exists(srcp):
                outp = os.path.join(dest_dir, sanitize(f"{system}_{out_suffix}"))
                shutil.copyfile(srcp, outp)
                copied.append(os.path.relpath(outp, cache))

    for rel in copied:
        run(["git", "add", "--", rel], cwd=cache, check=True)

    status = run(["git", "status", "--porcelain"], cwd=cache).stdout
    staged = [l for l in status.splitlines() if l.strip() and not l.startswith("??")]
    if not staged:
        print(json.dumps({"ok": True, "unchanged": True, "repo": repo, "dir": rel_dir, "file": out_name}, ensure_ascii=False))
        return

    token = pub.get("token")
    auth_repo = (
        repo.replace("https://", f"https://{pub.get('user') or 'oauth2'}:{token}@") if token else None
    )

    run(
        [
            "git",
            "-c",
            "user.name=" + (pub.get("gitUser") or "webapp-walkthrough"),
            "-c",
            "user.email=" + (pub.get("gitEmail") or "walkthrough@local"),
            "commit",
            "-m",
            commit_msg,
        ],
        cwd=cache,
        check=True,
    )
    sha = run(["git", "rev-parse", "--short", "HEAD"], cwd=cache).stdout.strip()

    push = run(["git", *_auth_prefix(), "push", auth_repo or "origin", f"HEAD:{branch}"], cwd=cache)
    if push.returncode != 0:
        print(json.dumps({"ok": False, "error": "推送失败", "detail": (push.stderr or push.stdout or "")[-600:], "commit": sha}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({
        "ok": True,
        "repo": repo,
        "branch": branch,
        "dir": rel_dir,
        "files": copied,
        "commit": sha,
        "message": commit_msg,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
