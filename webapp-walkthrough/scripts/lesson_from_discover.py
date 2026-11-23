"""把 autolesson.mjs 产出的 discover.json 转成可执行的教学脚本 lesson.json。

用法:
  python -I lesson_from_discover.py <工作目录> [--username admin] [--password 123456]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_path(url: str, base: str) -> str:
    if not url:
        return ""
    base = base.rstrip("/")
    if url.startswith(base):
        p = url[len(base):]
        return p if p.startswith("/") else "/" + p
    u = urlparse(url)
    return (u.path or "/") + (("?" + u.query) if u.query else "")


def feat_narration(it):
    title = it.get("title") or "该功能"
    page = it.get("pageTitle") or title
    bits = []
    tables = it.get("tables") or []
    if tables:
        bits.append(f"页面列表 {tables[0]} 行")
    btns = [b for b in (it.get("buttons") or []) if b and b not in (title,)]
    if btns:
        bits.append("可用操作有" + "、".join(btns[:4]))
    tail = ("，" + "，".join(bits)) if bits else ""
    return f"{title}：进入「{page}」页面{tail}。在这里可以完成与{title}相关的查看与操作。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--username", default=None)
    ap.add_argument("--password", default=None)
    a = ap.parse_args()

    wd = os.path.abspath(a.workdir)
    cfg = load(os.path.join(wd, "config.json"), {})
    disc = load(os.path.join(wd, "discover.json"))
    if not disc:
        print(json.dumps({"ok": False, "error": "缺少 discover.json"}, ensure_ascii=False))
        sys.exit(1)
    base = disc.get("baseUrl") or cfg.get("baseUrl") or ""
    system = cfg.get("systemName") or "系统"
    user = a.username or (cfg.get("autoLogin") or {}).get("username") or "admin"
    pwd = a.password or (cfg.get("autoLogin") or {}).get("password") or "123456"

    items = [x for x in disc.get("items", []) if x.get("url")]
    # 去重（同一路径只留一次）
    seen = set()
    uniq = []
    for it in items:
        p = to_path(it["url"], base)
        if p in seen:
            continue
        seen.add(p)
        it["_path"] = p
        uniq.append(it)

    steps = []
    if disc.get("needLogin"):
        steps.append({
            "title": "账号登录",
            "url": "/login",
            "narration": "首先登录系统。输入账号和密码，点击登录进入主界面。",
            "tips": f"演示账号：{user} / {pwd}",
            "actions": [
                {"type": "fill", "selector": "input[type=text], input:not([type])", "value": user},
                {"type": "fill", "selector": "input[type=password]", "value": pwd},
                {"type": "click", "selector": "button.el-button, button", "findSelector": "button", "label": "点击登录"},
                {"type": "wait", "ms": 1600},
            ],
            "holdMs": 1200,
        })

    for it in uniq:
        title = it.get("title") or it.get("pageTitle") or "功能"
        hl = {"selector": ".el-table"} if (it.get("tables") or []) else {"selector": ".page-title"}
        steps.append({
            "title": title,
            "url": it["_path"],
            "narration": feat_narration(it),
            "highlight": hl,
            "holdMs": 1600,
        })

    lesson = {
        "systemName": system,
        "baseUrl": base,
        "viewport": {"width": 1440, "height": 860},
        "cardMs": 1800,
        "intro": f"本期视频演示「{system}」的全部主要功能，按菜单顺序逐页讲解，跟着做就能上手。",
        "outro": f"以上就是「{system}」的功能演示，感谢观看。",
        "chapters": [
            {
                "title": "系统功能总览",
                "summary": "按左侧菜单顺序，逐页认识系统的全部功能。",
                "steps": steps,
            }
        ],
    }
    # 保留 config 里的 systemName/baseUrl 一致
    out = os.path.join(wd, "lesson.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(lesson, f, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "steps": len(steps), "lesson": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
