#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 毕设论文流水线编排

一次跑通：拉仓库 → 解析开题材料 → 从仓库材料建参考文献库 → 建写作工作区。
文献口径固定：开题题录优先、其余中文取仓库 `论文/论文推荐`，英文用 `开题材料/外文原文`，总数 15–35 篇。

    init    解析仓库号 → 拉仓库 → 解析开题材料 → 建文献库 → 建写作工作区
    status  看当前进度
    publish 命名 + 推送论文到仓库「论文/」

写作本身（大纲/成文/Visio图/降AIGC/质检/docx）由 Agent 按
ty-lw-skill 执行，不在本脚本内；不联网检索、不下载库外文献、不按关键词插引用。

用法：
    python run.py init 010
    python run.py init 010 --set 学号=0918230101 --set 指导教师=任长权
    python run.py refs harvest 010
    python run.py refs verify 010
    python run.py status 010
    python run.py publish 010 --dry-run
    python run.py publish 010
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import yx            # noqa: E402
import fetch as fetch_mod      # noqa: E402
import parse_materials as parse_mod  # noqa: E402
import publish as publish_mod  # noqa: E402
import zhuque as zhuque_mod    # noqa: E402
import plagiarism as plag_mod  # noqa: E402
import profiles as profiles_mod  # noqa: E402
import refs as refs_mod  # noqa: E402
import reflib as reflib_mod  # noqa: E402


def _cfg():
    return yx.load_config()


def ty_scripts(cfg: dict | None = None) -> Path:
    """ty-lw-skill 的 scripts 目录（论文生产引擎）。"""
    eng = (cfg or _cfg()).get("engine") or {}
    return Path(eng.get("ty_skill_dir", "")) / "scripts"


def run_dir(cfg: dict, repo_path: str) -> Path:
    return Path(cfg["paths"]["runs_root"]) / repo_path


def work_dir(cfg: dict, repo_path: str) -> Path:
    return run_dir(cfg, repo_path) / ".work"


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

CJK_RE = __import__("re").compile(r"[\u4e00-\u9fa5]")
COMMENT_RE = __import__("re").compile(r"<!--.*?-->", __import__("re").S)
FRONT_RE = __import__("re").compile(r"^---.*?^---", __import__("re").S | __import__("re").M)


def manuscript_real_chars(ms: Path) -> int:
    """统计稿件里真正写下的中文（剔除 front matter 与写作提示注释）。"""
    try:
        t = ms.read_text(encoding="utf-8-sig")
    except OSError:
        return 0
    t = COMMENT_RE.sub("", t)
    t = FRONT_RE.sub("", t)
    return len(CJK_RE.findall(t))


def cmd_init(args) -> int:
    cfg = _cfg()

    # 0) F01：拉取前先保护已写正文（否则 refresh/更新可能先毁稿再报错）
    pre_dest = Path(cfg["paths"]["runs_root"]) / (yx.resolve_repo(cfg, args.repo)["path"])
    if pre_dest.exists():
        n = fetch_mod.work_real_chars(pre_dest)
        if n >= 800 and not getattr(args, "reinit", False):
            print(f"[阻断] 工作区已有正文（约 {n} 个中文字），init 会重建骨架并覆盖它。", file=sys.stderr)
            print("  确认重建请加 --reinit（旧稿会自动备份）", file=sys.stderr)
            return 8
        if args.refresh and n >= 200 and not getattr(args, "force_refresh", False):
            print(f"[阻断] 工作区已有约 {n} 字正文，--refresh 会重建仓库。", file=sys.stderr)
            print("  确认可加 --force-refresh（旧目录会改名备份，不删除）", file=sys.stderr)
            return 8

    # 1) 拉仓库
    info = fetch_mod.fetch(args.repo, refresh=args.refresh, depth=1,
                           allow_work_loss=getattr(args, "force_refresh", False))
    print(f"[1/6] 仓库 {info['repo']}（{info['name']}）分支 {info['default_branch']} 已就绪")
    print(f"      {info['local_dir']}")
    if info.get("refresh_backup"):
        print(f"      旧目录已备份：{info['refresh_backup']}")

    if info["problems"]:
        print("\n[阻断] 材料不完整，先补齐再跑：", file=sys.stderr)
        for p in info["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 3

    # 2) 解析开题材料
    materials = Path(info["local_dir"]) / cfg["paths"]["materials_dir"]
    work = Path(info["work_dir"])
    work.mkdir(parents=True, exist_ok=True)

    student = parse_mod.parse(materials)
    evidence = student.pop("_evidence_text", "")

    # 续跑时保留上一次人工补的字段，避免重跑把 --set 的值冲掉
    previous_path = work / "student.json"
    if previous_path.exists():
        previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
        student["manual_fields"] = previous.get("manual_fields") or {}
        for key, value in student["manual_fields"].items():
            student["fields"][key] = value
    for item in args.set or []:
        if "=" in item:
            key, value = item.split("=", 1)
            student["fields"][key.strip()] = value.strip()
            student.setdefault("manual_fields", {})[key.strip()] = value.strip()
    if args.school:
        student["school"] = args.school
    student["continuation_options"] = {
        key: getattr(args, key, None) for key in
        ("school", "profile", "title_en", "allow_baseline", "no_auto_profile")
    }
    previous_path.write_text(json.dumps(student, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "materials-extracted.md").write_text(evidence, encoding="utf-8")

    # 文献库：中文只取仓库「论文/论文推荐」，英文只取「开题材料/外文原文」。
    # 不联网检索、不下载库外文献；题录缺项由 Agent 按题名精确匹配补录后 refs merge。
    library = reflib_mod.harvest(Path(info["local_dir"]), cfg)
    st = library["stats"]
    print(f"[2/6] 文献库  中文候选 {st['zh_total']} 篇"
          f"（题录齐全 {st['zh_complete']}，其中 {st['zh_source_link']} 篇缺出版项按链接著录；"
          f"缺作者 {st['zh_missing_author']}，缺来源 {st['zh_missing_source']}）"
          f"　英文 {st['en_total']} 篇")
    print(f"      要求：全文 {st['min_total']}–{st['max_total']} 条，英文 ≤ {st['max_english']} 篇"
          f"（必须含外文原文）；开题题录要全部用上；开题题录 {st['opening_total']} 条")
    if st["zh_missing_author"] or st["zh_missing_source"]:
        print(f"      [待补录] {reflib_mod.refs_dir(Path(info['local_dir'])) / 'missing-meta.md'}"
              f"　补完跑 refs merge {info.get('repo') or Path(info['local_dir']).name}")
    if st["zh_total"] < st["min_total"]:
        print(f"\n[阻断] 仓库只提供 {st['zh_total']} 篇推荐文献，加上开题题录 "
              f"{st['opening_total']} 条也凑不够 {st['min_total']} 条。", file=sys.stderr)
        print("  请先在仓库 论文/论文推荐 补齐文献（每篇一个 md），再重跑 init。", file=sys.stderr)
        return reflib_mod.EXIT_MATERIAL

    return complete_init(cfg, info, student, evidence, args)


def cmd_resume(args) -> int:
    """材料齐了继续：不重新拉库、不重建已存在的正文；文献库缺失时补建。"""
    cfg = _cfg()
    root = refs_mod.local_root(args.repo)
    work = root / ".work"
    student = json.loads((work / "student.json").read_text(encoding="utf-8-sig"))
    for key, value in (student.get("continuation_options") or {}).items():
        if key in ("school", "profile", "title_en", "allow_baseline", "no_auto_profile"):
            if not getattr(args, key, None) and value:
                setattr(args, key, value)
    evidence_path = work / "materials-extracted.md"
    evidence = evidence_path.read_text(encoding="utf-8-sig") if evidence_path.exists() else ""
    info = {"local_dir": str(root), "work_dir": str(work), "repo": root.name}
    if not (work / "refs" / "library.json").is_file():
        library = reflib_mod.harvest(root, cfg)
        st = library["stats"]
        print(f"[文献] 补建文献库：中文 {st['zh_total']} 篇（齐全 {st['zh_complete']}），"
              f"英文 {st['en_total']} 篇")
    return complete_init(cfg, info, student, evidence, args)


def complete_init(cfg, info, student, evidence, args) -> int:
    work = Path(info["work_dir"])
    # 学校以抬头识别为准，--school 可覆盖
    school = (args.school or student.get("school") or "").strip()
    if not school:
        print("[阻断] 从材料里认不出学校抬头。请用 --school 指定学校全名。", file=sys.stderr)
        return 6
    student["school"] = school

    # 3) 格式档案：显式 > 档案库 > 仓库模板自动逆向 > 基线
    try:
        prof = profiles_mod.resolve(school, explicit=args.profile,
                                    repo_dir=info["local_dir"],
                                    auto_extract=not args.no_auto_profile,
                                    allow_baseline=args.allow_baseline,
                                    cfg=cfg)
    except profiles_mod.ProfileError as e:
        print(f"[阻断] {e}", file=sys.stderr)
        return 7

    mismatch = profiles_mod.check_school_match(prof["path"], school)
    if mismatch:
        if prof["source"] == "baseline":
            # 回退基线时校名不一致是预期内的：封面校名由 --school 覆盖，
            # 但排版仍是别的学校的，必须明确告警而不是静默通过。
            for m in mismatch:
                print(f"[警告] {m}（已按 --allow-baseline 强制继续）", file=sys.stderr)
            prof.setdefault("warnings", []).append(
                "使用了别的学校的排版基线，封面校名会改对，但页边距/字体/分节等格式可能不符。"
            )
        else:
            print("[阻断] 格式档案与学校不匹配：", file=sys.stderr)
            for m in mismatch:
                print(f"  - {m}", file=sys.stderr)
            return 7

    lint_res = profiles_mod.lint(prof["path"], cfg)
    if not lint_res.get("ok"):
        print("[阻断] 格式档案体检未通过（先修档案再开工）：", file=sys.stderr)
        for e in (lint_res.get("errors") or []):
            print(f"  [ERROR] {e}", file=sys.stderr)
        return 7

    # 4) 人工补字段
    for item in args.set or []:
        if "=" not in item:
            print(f"[警告] 忽略无法解析的 --set：{item}", file=sys.stderr)
            continue
        k, v = item.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        student["fields"][k] = v
        student.setdefault("manual_fields", {})[k] = v

    student["missing_required"] = [k for k in parse_mod.REQUIRED
                                   if not student["fields"].get(k)]
    student["profile"] = {
        "path": prof["path"],
        "source": prof["source"],
        "warnings": prof.get("warnings") or [],
        "lint_warnings": lint_res.get("warnings") or [],
    }

    (work / "student.json").write_text(
        json.dumps(student, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "materials-extracted.md").write_text(evidence, encoding="utf-8")

    f = student["fields"]
    print(f"[3/6] 材料解析完成  学校={school}  任务书版式={student['template']}")
    print(f"      题目  : {f.get('题目')}")
    print(f"      姓名  : {f.get('姓名')}   学号: {f.get('学号')}")
    print(f"      学院  : {f.get('学院')}   专业: {f.get('专业')}")
    print(f"      教师  : {f.get('指导教师')}")
    print(f"      参考文献 {len(student['references'])} 条")

    print(f"[4/6] 格式档案  {prof['source']}  {prof['path']}")
    for w in prof.get("warnings") or []:
        print(f"      [提醒] {w}", file=sys.stderr)
    if lint_res.get("warnings"):
        print(f"      [档案 WARN] {len(lint_res['warnings'])} 条（不影响开工，交付报告需列出）")

    # 5) 缺字段处理
    if student["missing_required"]:
        print("\n[需要你补] 以下字段材料里没有，无法自动获取（不会编造）：", file=sys.stderr)
        for k in student["missing_required"]:
            print(f"  - {k}", file=sys.stderr)
        print("\n补齐后重跑，或直接带上："
              "--set 学号=xxx --set 专业=xxx --set 指导教师=xxx", file=sys.stderr)
        return 4

    # 6) 覆盖保护：正文写过就不能被 init 冲掉
    ms = work / "manuscript.md"
    written = manuscript_real_chars(ms)
    if ms.exists() and written >= 800 and not args.reinit:
        lo, hi, en_cap = 15, 35, 3
        try:
            stats = (json.loads((work / "refs" / "library.json")
                               .read_text(encoding="utf-8-sig")).get("stats") or {})
            lo = int(stats.get("min_total", lo))
            hi = int(stats.get("max_total", hi))
            en_cap = int(stats.get("max_english", en_cap))
        except Exception:
            pass
        print(f"[继续] 保留现有稿件（约 {written} 个中文字），不重建、不覆盖。")
        print(f"请按 .work/refs/library.md 写作：开题题录全部要用上、其余中文取自库内，"
              f"英文 ≤ {en_cap} 篇（含外文原文），全文 {lo}–{hi} 条；写完跑 refs verify 再发布。")
        return 0

    backup_note = ""
    if ms.exists() and args.reinit:
        import datetime as _dt
        bak = ms.with_suffix(f".md.bak-{_dt.datetime.now():%Y%m%d-%H%M%S}")
        ms.replace(bak)
        backup_note = f"（旧稿已备份：{bak.name}）"

    # 7) 建写作工作区
    if args.skip_prepare:
        print("[5/6] 跳过建工作区")
    else:
        rc = prepare_workspace(cfg, student, work, args, profile_path=prof["path"])
        if rc != 0:
            return rc
        print(f"[5/6] 写作工作区已建好：{work} {backup_note}")

    print("[6/6] 下一步：按 ty-lw-skill 写论文，完成后执行")
    print(f"      python run.py refs verify {info['repo']}")
    print(f"      python run.py detect {info['repo']}")
    print(f"      python run.py publish {info['repo']}")
    return 0


def prepare_workspace(cfg: dict, student: dict, work: Path, args,
                      profile_path: str | None = None) -> int:
    new_project = ty_scripts(cfg) / "new_project.py"
    if not new_project.exists():
        print(f"[错误] 找不到 {new_project}，请确认 ty-lw-skill 已安装", file=sys.stderr)
        return 5

    f = student["fields"]
    title_en = args.title_en or f.get("题目_en") or ""
    cmd = [
        sys.executable, str(new_project), str(work),
        "--title", f.get("题目") or "",
        "--name", f.get("姓名") or "",
        "--student-id", f.get("学号") or "",
        "--college", f.get("学院") or "",
        "--major", f.get("专业") or "",
        "--advisor", f.get("指导教师") or "",
        "--school", student.get("school") or "",
    ]
    if profile_path:
        cmd += ["--profile", str(profile_path)]
    if title_en:
        cmd += ["--title-en", title_en]
    # 只在明确要求重建时加 --force：它会清空已写好的 manuscript.md
    if getattr(args, "reinit", False):
        cmd += ["--force"]

    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("[错误] new_project.py 执行失败：", file=sys.stderr)
        print((p.stderr or p.stdout)[:1500], file=sys.stderr)
        return 5

    if not title_en:
        print("[提醒] 没有英文题目。论文封面需要中英文题目，请补 --title-en 或让 Agent 翻译后回填。",
              file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(args) -> int:
    cfg = _cfg()
    repo = yx.resolve_repo(cfg, args.repo)
    d = run_dir(cfg, repo["path"])
    w = work_dir(cfg, repo["path"])

    checks = {
        "仓库已拉取": d.is_dir(),
        "student.json": (w / "student.json").exists(),
        "materials-extracted.md": (w / "materials-extracted.md").exists(),
        "manuscript.md": (w / "manuscript.md").exists(),
        "outline.md": (w / "outline.md").exists(),
        "figs 目录": (w / "figs").is_dir(),
        "论文.docx": (w / "output" / "论文.docx").exists(),
        "论文.pdf": (w / "output" / "论文.pdf").exists(),
        "可编辑版.docx": (w / "output" / "论文_可编辑版.docx").exists(),
    }
    print(f"仓库 {repo['path']}（{repo['name']}）")
    print(f"目录 {d}")
    print(f"工作区 {w}\n")
    for k, v in checks.items():
        print(f"  {'✓' if v else '·'} {k}")

    if (w / "student.json").exists():
        s = json.loads((w / "student.json").read_text(encoding="utf-8-sig"))
        print("\n字段：")
        for k, v in s.get("fields", {}).items():
            print(f"  {k}: {v or '(空)'}")
        if s.get("missing_required"):
            print(f"\n[待补] {'、'.join(s['missing_required'])}")
        prof = s.get("profile") or {}
        if prof:
            print(f"\n格式档案（{prof.get('source')}）：{prof.get('path')}")
            for x in prof.get("warnings") or []:
                print(f"  [提醒] {x}")

    lib_path = w / "refs" / "library.json"
    if lib_path.is_file():
        try:
            lib = json.loads(lib_path.read_text(encoding="utf-8-sig"))
            st = lib.get("stats") or {}
            print(f"\n文献库：中文 {st.get('zh_total')} 篇（齐全 {st.get('zh_complete')}，"
                  f"缺作者 {st.get('zh_missing_author')}，缺来源 {st.get('zh_missing_source')}）"
                  f"　英文 {st.get('en_total')} 篇")
            print(f"  要求：全文 {st.get('min_total')}–{st.get('max_total')} 条，"
                  f"英文 ≤ {st.get('max_english')} 篇（含外文原文）")
            vp = w / "refs" / "verify.json"
            if vp.is_file():
                v = json.loads(vp.read_text(encoding="utf-8-sig"))
                print(f"  稿件校验：{'通过' if v.get('ok') else '未通过'}"
                      f"（共 {v.get('total')} 条，中文 {v.get('zh_cited')}，英文 {v.get('en_cited')}）")
        except Exception as e:
            print(f"\n文献库：读取失败 {e}")
    else:
        print("\n文献库：未建（python run.py refs harvest " + repo["path"] + "）")

    # 工作区里的档案与实际学校是否一致
    local_prof = w / "format-profile.json"
    if local_prof.exists():
        try:
            d = json.loads(local_prof.read_text(encoding="utf-8-sig"))
            wb = d.get("word_budget") or {}
            print(f"  校名：{d.get('school')}　字数区间：{wb.get('min')}–{wb.get('max')}"
                  f"（{wb.get('enforce')}）")
        except Exception:
            pass
    return 0


# --------------------------------------------------------------------------
# detect / plagiarize / quality
# --------------------------------------------------------------------------

def _work_of(repo_query: str) -> Path:
    cfg = _cfg()
    repo = yx.resolve_repo(cfg, repo_query)
    return work_dir(cfg, repo["path"])


def cmd_detect(args) -> int:
    cfg = _cfg()
    w = _work_of(args.repo)
    ms = w / "manuscript.md"
    if not ms.exists():
        print(f"[错误] 找不到 {ms}，论文正文还没写。", file=sys.stderr)
        return 1

    qcfg = (cfg.get("quality") or {}).get("zhuque") or {}
    target = args.target if args.target is not None else qcfg.get("target_ai_rate", 0.10)
    chunk = int(qcfg.get("chunk_chars", 3000))

    result = zhuque_mod.detect(ms.read_text(encoding="utf-8-sig"), chunk_chars=chunk)
    js, md = zhuque_mod.save(result, w, target)

    print(f"AI 率：{result['ai_rate_pct']}%（目标 ≤ {round(target * 100, 1)}%）")
    print(f"需改写片段：{result['flagged_count']} / {result['segment_count']}")
    print(f"报告：{md}")
    return 0 if result["ai_rate"] <= target else 2


def cmd_plagiarize(args) -> int:
    cfg = _cfg()
    w = _work_of(args.repo)
    ms = w / "manuscript.md"
    if not ms.exists():
        print(f"[错误] 找不到 {ms}，论文正文还没写。", file=sys.stderr)
        return 1

    pcfg = (cfg.get("quality") or {}).get("plagiarism") or {}
    limit = args.limit or int(pcfg.get("max_candidates", 40))
    min_chars = int(pcfg.get("min_sentence_chars", 25))

    cand = plag_mod.build_candidates(ms.read_text(encoding="utf-8-sig"),
                                     limit=limit, min_chars=min_chars)
    pdir = w / "quality" / "plagiarism"
    pdir.mkdir(parents=True, exist_ok=True)
    out = pdir / "candidates.json"
    out.write_text(json.dumps(cand, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"待查句：{cand['checked_candidates']} 条（全文 {cand['total_sentences']} 句）")
    print(f"清单：{out}")
    print("\n下一步：Agent 用联网搜索逐句查出处，把结果写到")
    print(f"  {pdir / 'results.json'}")
    print("然后执行： python run.py plagiarize-report " + args.repo)
    return 0


def cmd_plagiarize_report(args) -> int:
    w = _work_of(args.repo)
    pdir = w / "quality" / "plagiarism"
    cand_path = pdir / "candidates.json"
    res_path = pdir / "results.json"
    if not cand_path.exists():
        print(f"[错误] 找不到 {cand_path}，先跑 plagiarize", file=sys.stderr)
        return 1
    if not res_path.exists():
        print(f"[错误] 找不到 {res_path}，搜索结果还没写回来", file=sys.stderr)
        return 1

    cand = json.loads(cand_path.read_text(encoding="utf-8-sig"))
    results = json.loads(res_path.read_text(encoding="utf-8-sig"))
    summary = plag_mod.summarize(cand, results)
    (pdir / "report.md").write_text(plag_mod.render_report(summary, cand), encoding="utf-8")
    (pdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已查 {summary['checked']} 句，命中照抄 {len(summary['hits'])} 句，"
          f"抽样重复率 {summary['dup_rate_pct']}%")
    print(f"报告：{pdir / 'report.md'}")
    return 0


def cmd_quality(args) -> int:
    cfg = _cfg()
    w = _work_of(args.repo)
    qdir = w / "quality"

    print(f"工作区 {w}")
    if not qdir.is_dir():
        print("还没有做过质检。先跑： python run.py detect " + args.repo)
        return 0

    hist_path = qdir / "history.json"
    if hist_path.exists():
        hist = json.loads(hist_path.read_text(encoding="utf-8-sig"))
        target = ((cfg.get("quality") or {}).get("zhuque") or {}).get("target_ai_rate", 0.10)
        print(f"\n朱雀 AI 率历史（目标 ≤ {round(target*100,1)}%）：")
        for h in hist:
            flag = "✅" if h["ai_rate_pct"] <= target * 100 else "·"
            print(f"  {flag} {h['at']}  {h['ai_rate_pct']}%  ({h['chars']} 字)")

    rep = qdir / "plagiarism" / "report.md"
    print(f"\n查重报告：{'有 → ' + str(rep) if rep.exists() else '未做'}")
    return 0


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------

def _sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_publish(args) -> int:
    cfg = _cfg()
    w = _work_of(args.repo)
    ms = w / "manuscript.md"

    # 闸门 0：参考文献必须按口径来自仓库（中文 论文/论文推荐，英文 外文原文）且不少于下限
    ok_refs, refs_report = reflib_mod.verify(w.parent, cfg)
    if not ok_refs:
        if args.force:
            print("[警告] 参考文献闸门未通过，但已按 --force 继续：", file=sys.stderr)
            for r in refs_report.get("problems") or []:
                print(f"  - {r}", file=sys.stderr)
        else:
            print("[阻断] 参考文献闸门未通过，拒绝上传：", file=sys.stderr)
            for r in refs_report.get("problems") or []:
                print(f"  - {r}", file=sys.stderr)
            print("修好后重跑： python run.py refs verify " + args.repo, file=sys.stderr)
            print("确要强行上传： 加 --force", file=sys.stderr)
            return 6
    else:
        print(f"[文献] 共 {refs_report['total']} 条（中文 {refs_report['zh_cited']}，"
              f"英文 {refs_report['en_cited']}），全部来自仓库文献库 ✅")

    # F03：质检闸门——报告缺失/损坏/缺字段/与当前稿件不一致/超标，一律阻断（--force 才放行）
    qdir = w / "quality"
    latest = qdir / "latest.json"
    target = ((cfg.get("quality") or {}).get("zhuque") or {}).get("target_ai_rate", 0.10)
    reasons: list[str] = []
    if not ms.exists():
        reasons.append("找不到 manuscript.md")
    if not latest.exists():
        reasons.append("没有朱雀检测报告（quality/latest.json）")
    else:
        try:
            q = json.loads(latest.read_text(encoding="utf-8-sig"))
        except Exception as e:
            q = None
            reasons.append(f"检测报告损坏，无法解析：{e}")
        if isinstance(q, dict):
            rate = q.get("ai_rate")
            if not isinstance(rate, (int, float)):
                reasons.append("检测报告缺少有效的 ai_rate 字段")
            elif rate > target:
                reasons.append(f"AI 率 {round(rate * 100, 2)}% 高于目标 {round(target * 100, 1)}%")
            if ms.exists():
                cur = _sha256_file(ms)
                sha = q.get("manuscript_sha256")
                if not sha:
                    reasons.append("检测报告没有稿件指纹（旧版报告），请在当前稿件上重跑 detect")
                elif sha != cur:
                    reasons.append("检测报告与当前稿件不一致（稿件改过），请重跑 detect")

    if reasons:
        if args.force:
            print("[警告] 质检闸门未通过，但已按 --force 继续：", file=sys.stderr)
            for r in reasons:
                print(f"  - {r}", file=sys.stderr)
        else:
            print("[阻断] 质检闸门未通过，拒绝上传：", file=sys.stderr)
            for r in reasons:
                print(f"  - {r}", file=sys.stderr)
            print("修好后重跑： python run.py detect " + args.repo, file=sys.stderr)
            print("确要强行上传： 加 --force", file=sys.stderr)
            return 6
    else:
        print(f"[质检] 朱雀 AI 率 {round(q['ai_rate']*100,2)}% ✅ 且与当前稿件一致")

    naming = cfg.get("naming") or "{学号}_{姓名}_{专业}_{题目}"
    p = publish_mod.plan(args.repo, w, naming, branch=args.branch)
    result = publish_mod.apply(p, args.dry_run, args.message)

    # F03：成功后落一份发布清单（构建身份）
    if not args.dry_run and result.get("pushed"):
        try:
            manifest = {
                "published_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "repo": p["repo"], "branch": p["branch"], "basename": p["basename"],
                "commit": result.get("commit"),
                "manuscript_sha256": _sha256_file(ms) if ms.exists() else None,
                "profile_sha256": _sha256_file(w / "format-profile.json")
                if (w / "format-profile.json").exists() else None,
                "artifacts": {Path(f["to"]).name: f.get("size") for f in p["files"]},
                "ai_rate": (json.loads(latest.read_text(encoding="utf-8-sig")).get("ai_rate")
                            if latest.exists() else None),
                "references": {"total": refs_report.get("total"),
                               "zh_cited": refs_report.get("zh_cited"),
                               "en_cited": refs_report.get("en_cited"),
                               "min_total": refs_report.get("min_total")},
            }
            (w / "release-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------
# profile（转发给 profiles.py）
# --------------------------------------------------------------------------

def cmd_profile(args) -> int:
    return profiles_mod.main(args.rest or ["list"])


def cmd_refs(args) -> int:
    rest = args.rest or []
    if rest and rest[0] in ("harvest", "merge", "verify", "lib"):
        return reflib_mod.main(rest)
    return refs_mod.main(rest or ["--help"])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="毕设论文流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="拉仓库、解析开题材料、按仓库材料建参考文献库并建工作区")
    p_init.add_argument("repo")
    p_init.add_argument("--refresh", action="store_true", help="备份现有目录后重新克隆")
    p_init.add_argument("--force-refresh", action="store_true", help="有正文也强行刷新（旧目录改名备份）")
    p_init.add_argument("--set", action="append", metavar="字段=值",
                        help="人工补齐字段，可重复")
    p_init.add_argument("--title-en", help="英文题目")
    p_init.add_argument("--school", help="覆盖从材料识别出的学校名")
    p_init.add_argument("--profile", help="直接指定格式档案 json（优先于档案库）")
    p_init.add_argument("--allow-baseline", action="store_true",
                        help="该校没有档案时，允许回退内置基线（会告警）")
    p_init.add_argument("--no-auto-profile", action="store_true",
                        help="不自动从仓库里的模板逆向生成档案")
    p_init.add_argument("--reinit", action="store_true",
                        help="重建骨架；会先备份已写好的 manuscript.md")
    p_init.add_argument("--skip-prepare", action="store_true", help="只解析材料，不建工作区")
    p_init.set_defaults(func=cmd_init)

    p_prof = sub.add_parser("profile", help="学校格式档案库（list/check/show/extract/spec）")
    p_prof.add_argument("rest", nargs=argparse.REMAINDER)
    p_prof.set_defaults(func=cmd_profile)

    p_resume = sub.add_parser("resume", help="材料齐后继续（不重新拉库，文献库缺失时补建）")
    p_resume.add_argument("repo")
    p_resume.add_argument("--set", action="append", metavar="字段=值")
    p_resume.add_argument("--school")
    p_resume.add_argument("--profile")
    p_resume.add_argument("--title-en")
    p_resume.add_argument("--allow-baseline", action="store_true")
    p_resume.add_argument("--no-auto-profile", action="store_true")
    p_resume.add_argument("--reinit", action="store_true", help="明确重建骨架并备份旧稿")
    p_resume.add_argument("--skip-prepare", action="store_true")
    p_resume.set_defaults(func=cmd_resume)

    p_refs = sub.add_parser("refs", help="文献库：harvest/merge/verify/lib；用户补件 accept/request")
    p_refs.add_argument("rest", nargs=argparse.REMAINDER)
    p_refs.set_defaults(func=cmd_refs)

    p_st = sub.add_parser("status", help="查看进度")
    p_st.add_argument("repo")
    p_st.set_defaults(func=cmd_status)

    p_pub = sub.add_parser("publish", help="命名并推送论文")
    p_pub.add_argument("repo")
    p_pub.add_argument("--dry-run", action="store_true")
    p_pub.add_argument("--branch", help="推送目标分支（默认仓库默认分支）")
    p_pub.add_argument("--message")
    p_pub.add_argument("--force", action="store_true", help="参考文献闸门或朱雀 AI 率未过也强制上传")
    p_pub.set_defaults(func=cmd_publish)

    p_det = sub.add_parser("detect", help="朱雀 AIGC 检测")
    p_det.add_argument("repo")
    p_det.add_argument("--target", type=float, default=None, help="AI 率目标，如 0.10")
    p_det.set_defaults(func=cmd_detect)

    p_pl = sub.add_parser("plagiarize", help="生成联网溯源待查句清单")
    p_pl.add_argument("repo")
    p_pl.add_argument("--limit", type=int, default=None)
    p_pl.set_defaults(func=cmd_plagiarize)

    p_pr = sub.add_parser("plagiarize-report", help="汇总查重结果出报告")
    p_pr.add_argument("repo")
    p_pr.set_defaults(func=cmd_plagiarize_report)

    p_q = sub.add_parser("quality", help="查看质检历史")
    p_q.add_argument("repo")
    p_q.set_defaults(func=cmd_quality)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except yx.YunxiaoError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except zhuque_mod.ZhuqueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except profiles_mod.ProfileError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"[错误] 文件不存在：{e.filename}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[中断] 已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
