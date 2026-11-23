"""为教学视频生成讲解：教学讲稿 / 功能点清单 / 字幕 / 配音音轨 / 时间线。

用法:
  python -I narrate.py <工作目录> [--script narration.json]

讲解词优先级：自定义 --script 的 steps > lesson.json 每步 narration > 按页面内容自动生成。
intro / outro 优先级：--script > lesson.json > 自动生成。
"""
import json
import os
import subprocess
import sys
import wave

import numpy as np

SR = 22050


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_steps(path):
    steps = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))
    return steps


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data, rate


def write_wav(path, data, rate=SR):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.astype(np.int16).tobytes())


def short(text, n=22):
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def auto_step_text(step):
    """无 lesson.narration 时的自动讲解：功能点名 + 页面要素。"""
    title = step.get("title") or step.get("tab") or step.get("module") or "该功能"
    c = step.get("content") or {}
    bits = []
    heads = c.get("heads") or []
    if heads:
        bits.append(f"当前页面为「{short(heads[0], 16)}」")
    tables = c.get("tables") or []
    if tables:
        bits.append(f"列表 {tables[0]['rows']} 行")
    kpis = c.get("kpis") or []
    if kpis:
        bits.append(f"关键指标 {len(kpis)} 项")
    if step.get("filled"):
        bits.append(f"输入「{short(step['filled']['value'], 10)}」后查询")
    errors = [i for i in step.get("issues", []) if i.get("level") == "error"]
    if errors:
        bits.append("页面出现异常，详见讲解稿")
    if not bits:
        bits.append("页面展示正常")
    return f"{title}，{'，'.join(bits)}。"


def auto_intro(meta, steps, lesson):
    n_chap = meta.get("chapterCount") or meta.get("moduleCount") or 0
    n_feat = meta.get("featureCount") or len(steps)
    return (
        f"大家好，本期视频带你完整掌握「{meta.get('system', '系统')}」的全部功能。"
        f"我们按真实操作顺序，分 {n_chap} 个章节、{n_feat} 个功能点逐一演示，"
        "跟着做就能上手。"
    )


def auto_outro(meta, steps, lesson):
    errors = [
        (s.get("module"), s.get("tab"), i["msg"])
        for s in steps
        for i in s.get("issues", [])
        if i.get("level") == "error"
    ]
    n_feat = meta.get("featureCount") or len(steps)
    if not errors:
        return f"以上就是「{meta.get('system', '系统')}」{n_feat} 个功能点的完整教学，祝使用顺利。"
    return (
        f"以上就是「{meta.get('system', '系统')}」{n_feat} 个功能点的完整教学。"
        f"演示中发现 {len(errors)} 处异常，建议优先排查 {errors[0][0]} 模块。"
    )


def _find_ffmpeg():
    import shutil

    for c in [
        "ffmpeg",
        r"C:/Users/<user>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe",
    ]:
        if c == "ffmpeg":
            p = shutil.which("ffmpeg")
            if p:
                return p
        elif os.path.exists(c):
            return c
    return None


def _read_audio_any(path):
    """读 wav；mp3/webm 先用 ffmpeg 转 22050Hz 单声道 wav 再读。"""
    if path.lower().endswith(".wav"):
        return read_wav(path)
    ff = _find_ffmpeg()
    if not ff:
        raise RuntimeError("需要 ffmpeg 才能把 mp3 转成 wav")
    wav = path.rsplit(".", 1)[0] + "_sapi.wav"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", path, "-ar", str(SR), "-ac", "1", wav], check=True)
    return read_wav(wav)


def synth_sapi(workdir, jobs, voice, rate):
    want = (voice.get("name") if isinstance(voice, dict) else voice) or "Microsoft Huihui Desktop"
    jobs_path = os.path.join(workdir, "tts_jobs.json")
    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"id": j["id"], "text": j["text"], "out": j["out"].replace("\\", "/")} for j in jobs],
            f,
            ensure_ascii=False,
        )

    ps = f"""Add-Type -AssemblyName System.Speech
$jobs = Get-Content -Raw -Encoding UTF8 "{jobs_path.replace('\\', '/')}" | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | ForEach-Object {{ $_.VoiceInfo.Name }}
$want = "{want}"
if ($voices -contains $want) {{ $s.SelectVoice($want) }}
else {{
  $zh = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'zh*' }} | Select-Object -First 1
  if ($zh) {{ $s.SelectVoice($zh.VoiceInfo.Name) }}
}}
$s.Rate = {int(rate)}
foreach ($j in $jobs) {{
  $s.SetOutputToWaveFile($j.out)
  $s.Speak($j.text)
}}
$s.Dispose()
Write-Output "TTS_OK"
"""
    ps_path = os.path.join(workdir, "tts.ps1")
    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(ps)

    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "TTS_OK" not in (proc.stdout or ""):
        print("[narrate] SAPI TTS 失败:", (proc.stderr or proc.stdout or "")[:400])
        return {}

    out = {}
    for j in jobs:
        if os.path.exists(j["out"]):
            data, rate_hz = read_wav(j["out"])
            out[j["id"]] = {"data": data, "rate": rate_hz, "dur": len(data) / rate_hz}
    return out


def synth_edge(workdir, jobs, voice):
    """edge-tts 神经音色（自然度高，需联网）。name 形如 zh-CN-YunxiNeural。"""
    try:
        import asyncio

        import edge_tts
    except Exception as e:  # noqa
        print("[narrate] edge-tts 不可用:", e)
        return {}

    vname = voice.get("name") or "zh-CN-XiaoxiaoNeural"
    erate = voice.get("edgeRate") or voice.get("rate")
    if isinstance(erate, (int, float)):
        erate = f"{int(float(erate) * 5):+d}%"
    erate = erate or "+0%"
    vol = voice.get("volume") or "+0%"
    pitch = voice.get("pitch") or "+0Hz"

    async def _one(text, out_path):
        comm = edge_tts.Communicate(text, vname, rate=erate, volume=vol, pitch=pitch)
        await comm.save(out_path)

    out = {}
    for j in jobs:
        mp3 = j["out"].rsplit(".", 1)[0] + ".mp3"
        try:
            asyncio.run(_one(j["text"], mp3))
            data, rate_hz = _read_audio_any(mp3)
            out[j["id"]] = {"data": data, "rate": rate_hz, "dur": len(data) / rate_hz}
        except Exception as e:  # noqa
            print(f"[narrate] edge 合成失败 {j['id']}: {e}")
            return {}
    print(f"[narrate] edge 音色 {vname} rate={erate}")
    return out


def synth(workdir, jobs, voice, rate):
    if not jobs:
        return {}
    name = str(voice.get("name") or "")
    engine = voice.get("engine") or ("edge" if name.startswith("zh-CN-") else "sapi")
    if engine == "edge":
        r = synth_edge(workdir, jobs, voice)
        if r:
            return r
        print("[narrate] edge 失败，回退 SAPI 离线音色")
    return synth_sapi(workdir, jobs, voice, rate)



def human_time(iso):
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def fmt_ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    script_path = None
    if "--script" in sys.argv:
        script_path = sys.argv[sys.argv.index("--script") + 1]

    cfg = load_json(os.path.join(workdir, "config.json"), {})
    meta = load_json(os.path.join(workdir, "run", "meta.json"), {})
    steps = load_steps(os.path.join(workdir, "run", "steps.jsonl"))
    custom = load_json(script_path, {}) if script_path else {}
    lesson = load_json(os.path.join(workdir, "lesson.json"), {}) or {}

    total_ms = meta.get("totalMs", 0)

    # 每段画面时长（录制时间线）
    content = []
    for idx, s in enumerate(steps):
        if idx + 1 < len(steps):
            dur = max((steps[idx + 1]["t"] - s["t"]) / 1000.0, 0.6)
        else:
            dur = max((total_ms - s["t"]) / 1000.0, 0.9)
        content.append(dur)

    intro_text = custom.get("intro") or lesson.get("intro") or auto_intro(meta, steps, lesson)
    outro_text = custom.get("outro") or lesson.get("outro") or auto_outro(meta, steps, lesson)
    texts = []
    for s in steps:
        t = (custom.get("steps") or {}).get(str(s["i"])) or s.get("narration")
        texts.append(t if t else auto_step_text(s))

    os.makedirs(os.path.join(workdir, "run", "tts"), exist_ok=True)
    jobs = [{"id": "intro", "text": intro_text, "out": os.path.join(workdir, "run", "tts", "intro.wav")}]
    for i, t in enumerate(texts):
        jobs.append(
            {"id": f"s{i + 1}", "text": t, "out": os.path.join(workdir, "run", "tts", f"s{i + 1}.wav")}
        )
    jobs.append({"id": "outro", "text": outro_text, "out": os.path.join(workdir, "run", "tts", "outro.wav")})

    voice_cfg = cfg.get("voice") or {}
    voice = voice_cfg.get("name", "Microsoft Huihui Desktop")
    rate = voice_cfg.get("rate", 0)
    audio = synth(workdir, jobs, voice_cfg, rate)

    dur = lambda k: audio.get(k, {}).get("dur", 0.0)

    # 时间线：leadIn + 每段 max(画面, 配音+0.8)
    lead_in = max(1.4, dur("intro") + 0.8)
    timeline = []
    cursor = lead_in
    for i, s in enumerate(steps):
        pad = max(0.0, (dur(f"s{i + 1}") + 0.8) - content[i])
        start = cursor
        timeline.append(
            {
                "i": s["i"],
                "chapter": s.get("chapter") or s.get("module"),
                "chapterNo": s.get("chapterNo"),
                "module": s.get("module"),
                "tab": s.get("tab"),
                "title": s.get("title") or s.get("tab"),
                "card": bool(s.get("card")),
                "videoStart": round(start, 3),
                "contentDur": round(content[i], 3),
                "pad": round(pad, 3),
                "audioStart": round(start + 0.3, 3),
                "audioDur": round(dur(f"s{i + 1}"), 3),
            }
        )
        cursor = start + content[i] + pad

    outro_start = cursor + 0.4
    total = outro_start + max(dur("outro"), 1.0) + 0.8

    # 混音
    mixed = np.zeros(int(total * SR) + 2 * SR, dtype=np.float32)

    def put(key, at):
        if key not in audio:
            return
        data = audio[key]["data"].astype(np.float32) * 0.9
        start = int(at * SR)
        if start >= mixed.size:
            return
        end = min(start + len(data), mixed.size)
        mixed[start:end] += data[: end - start]

    if "intro" in audio:
        put("intro", 0.3)
    for i, item in enumerate(timeline):
        put(f"s{i + 1}", item["audioStart"])
    if "outro" in audio:
        put("outro", outro_start)

    peak = float(np.max(np.abs(mixed))) or 1.0
    if peak > 32000:
        mixed = mixed * (32000.0 / peak)
    audio_path = os.path.join(workdir, "run", "narration.wav")
    write_wav(audio_path, np.clip(mixed, -32768, 32767), SR)

    # 字幕
    srt = []
    seq = 1

    def cue(start, text):
        nonlocal seq
        srt.append(f"{seq}\n{fmt_ts(start)} --> {fmt_ts(start + 3.2)}\n{text}\n")
        seq += 1

    cue(0.2, intro_text)
    for i, item in enumerate(timeline):
        nxt = timeline[i + 1]["audioStart"] if i + 1 < len(timeline) else outro_start
        end = max(item["audioStart"] + max(item["audioDur"], 1.6), nxt - 0.05)
        srt.append(f"{seq}\n{fmt_ts(item['audioStart'])} --> {fmt_ts(end)}\n{texts[i]}\n")
        seq += 1
    cue(outro_start, outro_text)
    with open(os.path.join(workdir, "run", "narration.srt"), "w", encoding="utf-8") as f:
        f.write("\n".join(srt))

    payload = {
        "system": meta.get("system"),
        "mode": meta.get("mode", "teaching"),
        "leadIn": round(lead_in, 3),
        "outroStart": round(outro_start, 3),
        "totalSec": round(total, 3),
        "chapterCount": meta.get("chapterCount", 0),
        "featureCount": meta.get("featureCount", len(steps)),
        "steps": timeline,
        "contentDurs": [round(c, 3) for c in content],
    }
    with open(os.path.join(workdir, "run", "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    def tc(sec):
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    # 教学讲稿（按章节分组）
    lines = [
        f"# {meta.get('system')} 教学讲稿",
        "",
        f"- 录制时间：{human_time(meta.get('startedAt', ''))}",
        f"- 覆盖范围：{meta.get('chapterCount', 0)} 个章节 / {meta.get('featureCount', len(steps))} 个功能点",
        f"- 成片时长：约 {tc(total)}",
        "",
        "## 开场（00:00）",
        "",
        intro_text,
        "",
    ]
    cur_chap = None
    for i, item in enumerate(timeline):
        s = steps[i]
        if item.get("card"):
            lines += ["", f"## 第 {item.get('chapterNo')} 章　{item.get('chapter')}", "", texts[i], ""]
            lines.append("| 时间 | 功能点 | 讲解 | 要点 | 异常 |")
            lines.append("| --- | --- | --- | --- | --- |")
            cur_chap = item.get("chapter")
            continue
        errs = [x for x in s.get("issues", []) if x.get("level") == "error"]
        lines.append(
            f"| {tc(item['audioStart'])} | {item.get('title') or item.get('tab')} | {texts[i]} | "
            f"{short(s.get('tips') or '', 30) or '-'} | "
            f"{('; '.join(e['msg'][:40] for e in errs)) or '无'} |"
        )
    lines += ["", "## 收尾", "", outro_text, ""]
    with open(os.path.join(workdir, "run", "教学讲稿.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 功能点清单（checklist）
    feat_total = sum(1 for s in steps if not s.get("card"))
    done = 0
    cl = [
        f"# {meta.get('system')} 功能点清单",
        "",
        f"共 {meta.get('chapterCount', 0)} 个章节、{feat_total} 个功能点；状态由自动走查判定（页面正常 / 有异常）。",
        "",
    ]
    cur = None
    for i, s in enumerate(steps):
        if s.get("card"):
            cl += ["", f"## 第 {s.get('chapterNo')} 章　{s.get('chapter')}", ""]
            cl.append("| # | 功能点 | 页面 | 状态 | 截图 |")
            cl.append("| --- | --- | --- | --- | --- |")
            cur = s.get("chapter")
            continue
        done += 1
        errs = [x for x in s.get("issues", []) if x.get("level") == "error"]
        status = "❌ 异常" if errs else "✅ 正常"
        content = s.get("content") or {}
        heads = content.get("heads") or []
        page = short(heads[0], 20) if heads else "-"
        shot = s.get("shot") or "-"
        cl.append(f"| {done} | {s.get('title') or s.get('tab')} | {page} | {status} | {shot} |")
    with open(os.path.join(workdir, "run", "功能点清单.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(cl) + "\n")

    print(
        json.dumps(
            {
                "ok": True,
                "mode": payload["mode"],
                "segments": len(timeline),
                "features": feat_total,
                "audioSec": round(len(mixed) / SR, 1),
                "totalSec": round(total, 1),
                "voice": voice,
                "srt": "run/narration.srt",
                "script": "run/教学讲稿.md",
                "checklist": "run/功能点清单.md",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
