"""按「云效仓库号」一键制作系统使用教学视频（像 bishe-lw 一样只需给仓库号）。

流程：解析仓库号 → 克隆到 video/<项目号> → 自动启动系统 → 生成教学脚本
      → 录制/配音/合成 → 上传回云效（默认与论文同目录）。

用法:
  python -I make.py 007
  python -I make.py 007 --lesson lesson.json        # 用指定教学脚本
  python -I make.py 007 --url http://127.0.0.1:8080  # 系统已在运行，跳过启动
  python -I make.py 007 --no-publish                 # 只在本地产出，不上传
  python -I make.py 007 --voice zh-CN-YunxiNeural    # 指定音色

本地目录固定为 D:\\Tools_Home\\DeepseekHarness_Load\\video\\<项目号>\\：
  repo\\                 仓库克隆
  config.json            本次配置
  lesson.json            教学脚本（可手改后重跑）
  video_demo\\*.mp4      成片
  run\\                   录制/讲解中间产物
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lesson_from_discover  # noqa: E402
import provision  # noqa: E402
import repo as repo_tools  # noqa: E402

DEFAULT_ROOT = r"D:\Tools_Home\DeepseekHarness_Load\video"


def log(m):
    print(f"[make] {m}", flush=True)


def run_stream(cmd, cwd=None):
    log("运行: " + " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None)
    return p.returncode


def newest_mp4(folder: Path):
    if not folder.is_dir():
        return None
    fs = [f for f in folder.glob("*.mp4")]
    if not fs:
        return None
    fs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return fs[0]


def write_active(workdir: Path):
    root = Path(os.path.expanduser("~")) / "ego-walkthrough"
    root.mkdir(parents=True, exist_ok=True)
    (root / "active.txt").write_text(str(workdir).replace("\\", "/"), encoding="utf-8")


def build_config(repo, cfg_yx, branch, repo_dir, workdir, base, args, system):
    publish = {
        "enabled": not args.no_publish,
        "repo": repo_tools.clean_url(cfg_yx, repo["path"]),
        "branch": branch,
        "dir": args.publish_dir,
        "subdir": "",
        "filename": "{system}_教学视频_{date}.mp4",
        "includeDocs": True,
        "localRepo": str(repo_dir),
        "commit": "docs(演示视频): 新增《{system}》教学视频（{date}）",
    }
    return {
        "systemName": system,
        "baseUrl": base,
        "projectDir": str(workdir),
        "outDir": str(workdir / "video_demo"),
        "spaceName": "video-" + repo["path"],
        "autoLogin": {"username": args.username, "password": args.password},
        "login": {"required": False},
        "menuSelector": "aside .el-menu-item, aside a, nav a",
        "tabSelector": ".el-tabs__item, [role=tab]",
        "safeButtons": ["查询", "搜索", "刷新"],
        "denyButtons": ["删除", "退出", "注销", "支付"],
        "testQuery": "演示",
        "settleMs": 900,
        "humanize": True,
        "expandSubmenus": True,
        "publish": publish,
        "recorder": {"width": 1440, "height": 860, "jpegQuality": 70},
        "voice": {"engine": "edge", "name": args.voice, "rate": 1},
    }


def ensure_lesson(workdir: Path, repo_dir: Path, args):
    lesson_path = workdir / "lesson.json"
    if args.lesson:
        shutil.copyfile(os.path.abspath(args.lesson), lesson_path)
        log(f"使用指定教学脚本: {args.lesson}")
        return "given"
    if lesson_path.exists():
        log("沿用已有 lesson.json")
        return "existing"
    repo_lesson = repo_dir / "lesson.video.json"
    if repo_lesson.exists():
        shutil.copyfile(repo_lesson, lesson_path)
        log("使用仓库内 lesson.video.json")
        return "repo"
    # 自动生成：启动后枚举菜单
    log("未提供教学脚本，自动枚举菜单生成（autolesson）")
    write_active(workdir)
    ego = None
    for c in [r"C:/Program Files/Citro Labs/ego lite/Application"]:
        base = Path(c)
        if base.is_dir():
            vers = sorted([d for d in base.iterdir() if (d / "ego-browser.exe").exists()],
                          key=lambda d: [int(x) for x in "".join(ch if ch.isdigit() else " " for ch in d.name).split()] or [0])
            if vers:
                ego = str(vers[-1] / "ego-browser.exe")
    if not ego:
        raise RuntimeError("找不到 ego-browser，无法自动枚举菜单")
    rc = subprocess.run([ego, "nodejs", "-e", f"await import('file:///{str(HERE / 'autolesson.mjs').replace(chr(92), '/')}')"]).returncode
    if rc != 0:
        raise RuntimeError("autolesson 失败")
    lesson_from_discover.main([str(workdir), "--username", args.username, "--password", args.password])
    return "auto"


def main(argv):
    ap = argparse.ArgumentParser(description="按云效仓库号一键制作教学视频")
    ap.add_argument("repo", help="云效仓库号，如 007 / bishe007 / 010-题目")
    ap.add_argument("--lesson", default=None, help="指定教学脚本 lesson.json")
    ap.add_argument("--url", default=None, help="系统已运行时的地址；给了就跳过自动启动")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--workdir-root", default=os.environ.get("WEBAPP_VIDEO_ROOT", DEFAULT_ROOT))
    ap.add_argument("--publish-dir", default="论文", help="上传到仓库的哪个目录（默认：论文）")
    ap.add_argument("--reuse-repo", default=None, help="复用已有的本地仓库 clone（省去重复克隆 500MB+ 的仓库）")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="123456")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-record", action="store_true", help="只做讲解+合成+上传（复用已有 run 帧）")
    a = ap.parse_args(argv)

    cfg_yx, repo, branch = repo_tools.resolve(a.repo)
    log(f"仓库: {repo['path']} ({repo['name']}) 分支={branch}")

    root = Path(a.workdir_root)
    workdir = root / repo["path"]
    workdir.mkdir(parents=True, exist_ok=True)
    if a.reuse_repo:
        repo_dir = Path(os.path.abspath(a.reuse_repo))
        if not (repo_dir / ".git").exists():
            raise RuntimeError(f"--reuse-repo 不是 git 仓库: {repo_dir}")
        log(f"复用本地仓库: {repo_dir}")
    else:
        repo_dir = workdir / "repo"
        action = repo_tools.clone_or_update(cfg_yx, repo, branch, repo_dir, full=True)
        log(f"仓库已{('更新' if action == 'updated' else '克隆')}到 {repo_dir}")

    src = repo_dir / "源码" if (repo_dir / "源码").is_dir() else repo_dir

    server = None
    try:
        if a.url:
            base = a.url.rstrip("/")
            log(f"使用已有系统地址: {base}")
        else:
            server, base = provision.provision(src, a.port, workdir / "provision.log", log=log)

        system = re.sub(r"^\s*\d{3,4}\s*[-_、 ]*", "", repo.get("name") or "").strip() or repo["path"]
        cfg = build_config(repo, cfg_yx, branch, repo_dir, workdir, base, a, system)
        (workdir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"配置已写入 {workdir / 'config.json'}")

        mode = ensure_lesson(workdir, repo_dir, a)
        log(f"教学脚本: {mode}")

        run_all = [sys.executable, "-I", str(HERE / "run_all.py"), str(workdir)]
        if a.skip_record:
            run_all.append("--narrate-only")
        rc = run_stream(run_all)
        if rc != 0:
            raise RuntimeError(f"run_all 执行失败 (exit {rc})")

        vid = newest_mp4(workdir / "video_demo") or newest_mp4(workdir)
        print("\n[make] 完成")
        print(f"  工作目录: {workdir}")
        print(f"  教学脚本: {workdir / 'lesson.json'}")
        if vid:
            print(f"  成片: {vid}")
        if not a.no_publish:
            print(f"  已上传: {cfg['publish']['repo']} @ {cfg['publish']['dir']}（见上方 publish 日志）")
    finally:
        if server is not None and server.poll() is None:
            try:
                server.terminate()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as e:
        print(f"[make][错误] {e}", file=sys.stderr)
        raise SystemExit(1)
