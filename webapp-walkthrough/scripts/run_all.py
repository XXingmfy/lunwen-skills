"""一键走查：发现 → 驱动录制 → 讲解 → 成片。

用法:
  python -I run_all.py <工作目录> [--lesson lesson.json]
                                  [--discover-only] [--skip-discover]
                                  [--narrate-only] [--script narration.json]
                                  [--publish] [--no-publish] [--dry-run-publish]

工作目录里必须有 config.json。给了 --lesson（教学脚本）就走教学视频模式，
跳过 discover；否则走旧的逐选项卡走查模式（需要 plan.json）。
成片后若 config.publish.enabled 或加 --publish，则自动上传到云效指定目录（默认与论文同目录）。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

EGO_GLOBS = [
    r"C:/Program Files/Citro Labs/ego lite/Application/*/ego-browser.exe",
    r"C:/Program Files/Citro Labs/ego lite/Application/ego-browser.exe",
]
EGO_CANDIDATES = [
    "ego-browser",
    r"C:/Users/<user>/.local/share/ego/active_version_dir/ego-browser.exe",
]


def _ver_key(path):
    parts = re.findall(r"\d+", os.path.basename(os.path.dirname(path)))
    return tuple(int(p) for p in parts) if parts else (0,)


def find_ego():
    # 1) 优先扫描已安装的版本目录，取版本号最大者（避免 active_version_dir 指向旧版本）
    found = []
    for pattern in EGO_GLOBS:
        found.extend(glob.glob(pattern))
    found = [p for p in set(found) if os.path.isfile(p)]
    if found:
        found.sort(key=_ver_key, reverse=True)
        return found[0]
    # 2) 退回 PATH 与 junction
    for c in EGO_CANDIDATES:
        if c == "ego-browser":
            p = shutil.which("ego-browser")
            if p:
                return p
        elif os.path.exists(c):
            return c
    return None


def run_ego(ego, script, workdir):
    """ego 脚本从 stdin 读入，工作目录由 active.txt 指针决定。"""
    script_path = os.path.join(HERE, script)
    print(f"[run_all] ego -> {script}", flush=True)
    with open(script_path, "rb") as stdin:
        proc = subprocess.Popen(
            [ego, "nodejs"],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(line, flush=True)
                lines.append(line)
        proc.wait()
    if proc.returncode != 0:
        raise SystemExit(f"{script} 执行失败 (exit {proc.returncode})")
    return "\n".join(lines)


def run_py(script, args):
    cmd = [sys.executable, "-I", os.path.join(HERE, script)] + args
    print(f"[run_all] python → {script}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print((proc.stdout or "")[-1500:])
        print((proc.stderr or "")[-1500:])
        raise SystemExit(f"{script} 执行失败")
    tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    print(tail[-1] if tail else "(无输出)")
    return proc.stdout


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    workdir = os.path.abspath(sys.argv[1])
    flags = set(sys.argv[2:])
    script_file = None
    if "--script" in sys.argv:
        script_file = sys.argv[sys.argv.index("--script") + 1]
        flags.discard("--script")
    lesson_file = None
    if "--lesson" in sys.argv:
        lesson_file = sys.argv[sys.argv.index("--lesson") + 1]
        flags.discard("--lesson")

    cfg_path = os.path.join(workdir, "config.json")
    if not os.path.exists(cfg_path):
        raise SystemExit(f"缺少配置文件: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 教学脚本：复制到工作目录，run.mjs / narrate.py 会自动读取 lesson.json
    lesson_mode = bool(lesson_file) or os.path.exists(os.path.join(workdir, "lesson.json"))
    if lesson_file:
        src_lesson = os.path.abspath(lesson_file)
        if not os.path.exists(src_lesson):
            raise SystemExit(f"找不到教学脚本: {src_lesson}")
        shutil.copyfile(src_lesson, os.path.join(workdir, "lesson.json"))
    print(f"[run_all] 系统: {cfg.get('systemName')} · {cfg.get('baseUrl')} · 模式: {'教学视频' if lesson_mode else '自动走查'}")

    pub = cfg.get("publish") or {}
    should_publish = ("--publish" in sys.argv or pub.get("enabled")) and "--no-publish" not in sys.argv

    ego = find_ego()
    if not ego:
        raise SystemExit("找不到 ego-browser，请先安装 ego lite")

    # ego 脚本通过指针文件定位本次工作目录
    root = os.path.join(os.path.expanduser("~"), "ego-walkthrough")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "active.txt"), "w", encoding="utf-8") as f:
        f.write(workdir.replace("\\", "/"))

    if "--narrate-only" not in flags:
        if not lesson_mode and "--skip-discover" not in flags:
            run_ego(ego, "discover.mjs", workdir)
            if "--discover-only" in flags:
                print(f"[run_all] 走查计划已生成: {os.path.join(workdir, 'plan.json')}")
                return
        run_ego(ego, "run.mjs", workdir)

    narrate_args = [workdir]
    if script_file:
        narrate_args += ["--script", os.path.abspath(script_file)]
    run_py("narrate.py", narrate_args)
    out = run_py("assemble.py", [workdir])

    try:
        result = json.loads((out or "").strip().splitlines()[-1])
    except Exception:
        result = {}

    # 上传到云效（默认与论文同目录）
    if should_publish and result.get("video"):
        print(f"[run_all] 上传到云效: {pub.get('repo')} @ {pub.get('dir', '论文')}")
        pub_args = [workdir, "--video", result["video"]]
        if "--dry-run-publish" in sys.argv:
            pub_args.append("--dry-run")
        try:
            pout = run_py("publish.py", pub_args)
            try:
                pres = json.loads((pout or "").strip().splitlines()[-1])
                if pres.get("ok") and pres.get("commit"):
                    print(f"[run_all] 已上传：{pres.get('dir')}/{os.path.basename(pres.get('files', [''])[0])} (commit {pres.get('commit')})")
                elif pres.get("unchanged"):
                    print("[run_all] 云端已是最新，无变化")
            except Exception:
                pass
        except SystemExit as e:
            print(f"[run_all] 上传失败：{e}")
    elif should_publish and not result.get("video"):
        print("[run_all] 未找到成片，跳过上传")

    print("\n[run_all] 完成")
    if result.get("video"):
        print(f"  成片: {result['video']}")
    teach = os.path.join(workdir, "run", "教学讲稿.md")
    checklist = os.path.join(workdir, "run", "功能点清单.md")
    if os.path.exists(teach):
        print(f"  教学讲稿: {teach}")
    if os.path.exists(checklist):
        print(f"  功能点清单: {checklist}")
    if os.path.exists(os.path.join(workdir, "run", "讲解稿.md")):
        print(f"  讲解稿: {os.path.join(workdir, 'run', '讲解稿.md')}")
    print(f"  字幕: {os.path.join(workdir, 'run', 'narration.srt')}")
    print(f"  截图: {os.path.join(workdir, 'run', 'shots')}")


if __name__ == "__main__":
    main()
