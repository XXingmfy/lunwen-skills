"""把抽帧 + 讲解音频合成最终讲解视频。

用法:
  python -I assemble.py <工作目录>
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FF_CANDIDATES = [
    "ffmpeg",
    r"C:/Users/<user>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe",
]
FONT_CANDIDATES = [
    r"C:/Windows/Fonts/msyh.ttc",
    r"C:/Windows/Fonts/simhei.ttf",
    r"C:/Windows/Fonts/simsun.ttc",
]


def find_ffmpeg():
    import shutil

    for c in FF_CANDIDATES:
        if c == "ffmpeg":
            p = shutil.which("ffmpeg")
            if p:
                return p
        elif os.path.exists(c):
            return c
    return None


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_steps(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def card(width, height, title, subtitle, path):
    img = Image.new("RGB", (width, height), (15, 23, 42))
    d = ImageDraw.Draw(img)
    d.rectangle([0, height - 8, width, height], fill=(37, 99, 235))
    f1, f2 = font(int(height * 0.062)), font(int(height * 0.030))
    tw = d.textlength(title, font=f1)
    d.text(((width - tw) / 2, height * 0.40), title, font=f1, fill=(226, 232, 240))
    if subtitle:
        sw = d.textlength(subtitle, font=f2)
        d.text(((width - sw) / 2, height * 0.40 + int(height * 0.09)), subtitle, font=f2, fill=(148, 163, 184))
    img.save(path, quality=92)
    return path


def resolve_out_dir(cfg, workdir):
    """成片目录优先级：显式 outDir > 项目目录/video_demo > D:/video_demo。"""
    if cfg.get("outDir"):
        return cfg["outDir"]
    project = cfg.get("projectDir")
    if project:
        return project.replace("\\", "/").rstrip("/") + "/video_demo"
    return "D:/video_demo"


def main():
    workdir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    run = os.path.join(workdir, "run")
    cfg = load_json(os.path.join(workdir, "config.json"), {})
    meta = load_json(os.path.join(run, "meta.json"), {})
    timeline = load_json(os.path.join(run, "timeline.json"))
    index = load_json(os.path.join(run, "frames", "index.json"), {"frames": []})
    steps = load_steps(os.path.join(run, "steps.jsonl"))

    frames = index.get("frames", [])
    if not frames:
        print(json.dumps({"ok": False, "error": "没有抽到任何画面帧"}))
        sys.exit(1)
    if not timeline:
        print(json.dumps({"ok": False, "error": "缺少 timeline.json，请先运行 narrate.py"}))
        sys.exit(1)

    ff = find_ffmpeg()
    if not ff:
        print(json.dumps({"ok": False, "error": "找不到 ffmpeg"}))
        sys.exit(1)

    # 抽帧期间视口可能被重置，按出现最多的尺寸过滤，避免 concat 尺寸不一致
    from collections import Counter

    sizes = Counter((int(f.get("w") or 1280), int(f.get("h") or 720)) for f in frames)
    (w, h), _ = sizes.most_common(1)[0]
    frames = [f for f in frames if (int(f.get("w") or 1280), int(f.get("h") or 720)) == (w, h)]
    W, H = (w // 2) * 2, (h // 2) * 2

    total_ms = meta.get("totalMs", 0)
    content = timeline["contentDurs"]

    cards = os.path.join(run, "cards")
    os.makedirs(cards, exist_ok=True)
    is_teaching = meta.get("mode", "teaching") == "teaching"
    chap = meta.get("chapterCount", meta.get("moduleCount", 0))
    feat = meta.get("featureCount", len(steps))
    intro_sub = (
        f"{chap} 个章节 · {feat} 个功能点 · 真实操作教学"
        if is_teaching
        else f"{meta.get('moduleCount', 0)} 个模块 · {len(steps)} 个选项卡 · 自动化真实操作"
    )
    intro_card = card(W, H, meta.get("system", "系统演示"), intro_sub, os.path.join(cards, "intro.jpg"))
    outro_title = "教学演示结束" if is_teaching else "演示结束"
    outro_sub = (
        f"覆盖 {feat} 个功能点 · 发现异常 {meta.get('issueCount', 0)} 处"
        if is_teaching
        else f"发现异常 {meta.get('issueCount', 0)} 处"
    )
    outro_card = card(W, H, outro_title, outro_sub, os.path.join(cards, "outro.jpg"))

    # 逐段生成 concat 列表
    entries = []  # (absolute path, duration_sec)
    entries.append((intro_card, timeline["leadIn"]))

    for i, item in enumerate(timeline["steps"]):
        start_ms = steps[i]["t"]
        end_ms = start_ms + content[i] * 1000
        seg = [f for f in frames if start_ms <= f["t"] < end_ms]
        if not seg:
            seg = [f for f in frames if f["t"] <= end_ms][-1:] or [frames[0]]
        # 关键：把本步的帧按相对间隔归一到 content[i] 秒，
        # 保证每步画面时长 == 录制时长（否则首帧晚于步起点会造成整体音画漂移）。
        if len(seg) == 1:
            raw = [max(0.001, content[i])]
        else:
            raw = []
            for j, f in enumerate(seg):
                if j + 1 < len(seg):
                    raw.append(max(0.001, (seg[j + 1]["t"] - f["t"]) / 1000.0))
                else:
                    raw.append(max(0.001, (end_ms - f["t"]) / 1000.0))
        tot = sum(raw) or 1.0
        scale = content[i] / tot
        for j, f in enumerate(seg):
            entries.append((os.path.join(run, f["file"]), max(0.034, raw[j] * scale)))
        if item["pad"] > 0:
            entries.append((os.path.join(run, seg[-1]["file"]), item["pad"]))

    video_end = sum(d for _, d in entries)
    tail = max(0.8, timeline["totalSec"] - video_end)
    entries.append((outro_card, tail))

    list_path = os.path.join(run, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for path, d in entries:
            p = path.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{p}'\nduration {d:.3f}\n")
        f.write(f"file '{entries[-1][0].replace(chr(92), '/')}'\n")

    from datetime import datetime

    try:
        stamp = datetime.fromisoformat(meta.get("startedAt", "").replace("Z", "+00:00")).astimezone()
        stamp_s = stamp.strftime("%Y%m%d-%H%M")
    except Exception:
        stamp_s = datetime.now().strftime("%Y%m%d-%H%M")
    name = f"{meta.get('system', 'walkthrough')}" + ("_教学" if meta.get("mode", "teaching") == "teaching" else "") + f"_{stamp_s}"
    out_dir = resolve_out_dir(cfg, workdir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}.mp4")
    srt_path = os.path.join(run, "narration.srt")

    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
        "subtitles=narration.srt:force_style='FontName=Microsoft YaHei,FontSize=12,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101828,BorderStyle=1,Outline=1.2,"
        "Shadow=0.6,MarginV=30'"
    )

    cmd = [
        ff, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-i", "narration.wav",
        "-r", "30", "-fps_mode", "cfr",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        out_path,
    ]
    proc = subprocess.run(cmd, cwd=run, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not os.path.exists(out_path):
        print(json.dumps({"ok": False, "error": (proc.stderr or "")[-800:]}, ensure_ascii=False))
        sys.exit(1)

    size = os.path.getsize(out_path)
    print(
        json.dumps(
            {
                "ok": True,
                "video": out_path,
                "seconds": round(sum(d for _, d in entries), 1),
                "frames": len(entries),
                "sizeMB": round(size / 1024 / 1024, 2),
                "srt": srt_path,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
