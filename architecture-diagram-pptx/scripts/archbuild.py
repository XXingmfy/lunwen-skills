#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archbuild.py — 规格驱动的架构图生成器（PowerPoint 原生可编辑元素）

用法:
    python archbuild.py build  spec.json [--out DIR] [--png] [--strict]
    python archbuild.py check  spec.json
    python archbuild.py export deck.pptx [--out DIR] [--width 2560]
    python archbuild.py demo   [--out DIR] [--png]

设计约束见 ../references/design-spec.md，规格字段见 ../references/spec-schema.md。
PNG 导出依赖本机已安装的 Microsoft PowerPoint（COM）。LibreOffice 不被支持。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from lxml import etree

# ---------------------------------------------------------------- 画布与主题

CANVASES = {
    "16:9": (13.333, 7.5),
    "4:3": (10.0, 7.5),
    "a4l": (11.69, 8.27),
    "a4p": (8.27, 11.69),
}

THEME = {
    "ink": "1F2933",
    "muted": "5B6B7A",
    "faint": "8A99A8",
    "hairline": "D7DEE5",
    "band_fill": "F4F6F8",
    "band_line": "D7DEE5",
    "group_fill": "FFFFFF",
    "group_line": "C9D4DE",
    "box_fill": "FFFFFF",
    "box_line": "9AAAB8",
    "accent": "2F5D8A",
    "accent_fill": "E8EFF6",
    "warn": "A86A22",
    "warn_fill": "FBF1E4",
    "ok": "3F7A5E",
    "ok_fill": "EAF3EE",
    "flow": "6E8091",
    "white": "FFFFFF",
}

# tone -> (fill_key, line_key, text_key, bold)
TONES = {
    "default": ("box_fill", "box_line", "ink", False),
    "accent": ("accent_fill", "accent", "accent", False),
    "strong": ("accent", "accent", "white", True),
    "muted": ("band_fill", "hairline", "muted", False),
    "ghost": ("white", "hairline", "muted", False),
    "warn": ("warn_fill", "warn", "warn", False),
    "ok": ("ok_fill", "ok", "ok", False),
}

DEBUG = bool(os.environ.get("ARCHBUILD_DEBUG"))

FS = {  # 字号阶梯（pt）
    "title": 19.0,
    "subtitle": 9.5,
    "band": 10.5,
    "group": 9.0,
    "item": 11.5,
    "item_min": 8.0,
    "sub": 8.5,
    "sub_min": 7.0,
    "legend": 8.5,
    "note": 8.0,
    "flow": 8.0,
    "rail": 9.5,
}

LW = {"band": 0.75, "group": 0.75, "box": 0.9, "flow": 0.9, "hair": 0.75}

# ---------------------------------------------------------------- 文本度量


def _char_w(ch: str, size: float) -> float:
    """估算单字符宽度（pt）。CJK 按 1.0em，西文按比例。"""
    o = ord(ch)
    if o > 0x2E7F or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFF60:
        return size
    if ch in " .,:;'`|!il[](){}/\\":
        return size * 0.30
    if ch in "mwMW@%&":
        return size * 0.70
    if ch.isupper():
        return size * 0.66
    return size * 0.54


def text_w(s: str, size: float) -> float:
    return sum(_char_w(c, size) for c in s) * 1.03  # 3% 安全余量


def wrap_lines(text: str, size: float, avail_pt: float) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for hard in str(text).split("\n"):
        cur, curw = "", 0.0
        for ch in hard:
            cw = _char_w(ch, size) * 1.03
            if curw + cw > avail_pt and cur:
                out.append(cur)
                cur, curw = ch, cw
            else:
                cur += ch
                curw += cw
        out.append(cur)
    return out


@dataclass
class Box:
    id: str
    x: float
    y: float
    w: float
    h: float
    label: str = ""
    sub: str = ""
    tone: str = "default"
    shape: str = "rounded"      # rounded | rect | oval
    radius: float = 0.05
    kind: str = "item"          # band | group | item | free | rail
    pad: float = 0.07
    bold: bool = False
    parent: str | None = None
    # 计算后填充
    pt: float = FS["item"]
    sub_pt: float = FS["sub"]
    lines: list[str] = field(default_factory=list)
    sub_lines: list[str] = field(default_factory=list)
    overflow: bool = False

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.notes: list[str] = []

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warns.append(m)

    def ok(self, m: str) -> None:
        self.notes.append(m)

    def dump(self) -> str:
        lines = []
        for m in self.errors:
            lines.append(f"[ERROR] {m}")
        for m in self.warns:
            lines.append(f"[WARN ] {m}")
        for m in self.notes:
            lines.append(f"[INFO ] {m}")
        return "\n".join(lines) if lines else "[OK   ] 无问题"


# ---------------------------------------------------------------- 文字适配


def fit_text(b: Box, min_pt: float = FS["item_min"], sub_min: float = FS["sub_min"]) -> None:
    """在盒内放得下的最大字号；显式换行以锁定 PowerPoint 的渲染结果。"""
    if b.shape == "oval":
        avail_w = (min(b.w, b.h) * 0.70 - 2 * b.pad) * 72
        avail_h = (min(b.w, b.h) * 0.70 - 2 * b.pad) * 72
    else:
        avail_w = (b.w - 2 * b.pad) * 72
        avail_h = (b.h - 2 * b.pad) * 72
    avail_w = max(12.0, avail_w)
    avail_h = max(10.0, avail_h)

    has_sub = bool(b.sub)
    pt = FS["item"]
    while pt >= min_pt - 1e-6:
        lines = wrap_lines(b.label, pt, avail_w)
        spt = round(pt * 0.76, 1)
        spt = max(spt, sub_min)
        sub_lines = wrap_lines(b.sub, spt, avail_w) if has_sub else []
        h = len(lines) * pt * 1.16
        if sub_lines:
            h += 2.0 + len(sub_lines) * spt * 1.10
        if h <= avail_h:
            b.pt, b.sub_pt = pt, spt
            b.lines, b.sub_lines = lines, sub_lines
            b.overflow = False
            return
        pt -= 0.5

    b.pt = min_pt
    b.sub_pt = sub_min
    b.lines = wrap_lines(b.label, b.pt, avail_w)
    b.sub_lines = wrap_lines(b.sub, b.sub_pt, avail_w) if has_sub else []
    h = len(b.lines) * b.pt * 1.16
    if b.sub_lines:
        h += 2.0 + len(b.sub_lines) * b.sub_pt * 1.10
    b.overflow = h > avail_h + 0.5


def measure_label_w(s: str, pt: float, pad: float = 0.14) -> float:
    return text_w(s, pt) / 72.0 + pad


# ---------------------------------------------------------------- 规格解析


def _norm_item(raw, default_tone="default") -> dict:
    if isinstance(raw, str):
        return {"label": raw, "tone": default_tone}
    if not isinstance(raw, dict):
        raise ValueError(f"item 必须是字符串或对象: {raw!r}")
    if "label" not in raw:
        raise ValueError(f"item 缺少 label: {raw!r}")
    return raw


def _as_float(v, key, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字，收到 {v!r}")


# ---------------------------------------------------------------- 布局


def layout(spec: dict, rep: Report) -> tuple[list[Box], dict]:
    canvas = spec.get("canvas", "16:9")
    if isinstance(canvas, str):
        if canvas not in CANVASES:
            raise ValueError(f"未知画布 {canvas}，可选 {list(CANVASES)}")
        W, H = CANVASES[canvas]
    else:
        W = _as_float(canvas.get("w_in"), "canvas.w_in")
        H = _as_float(canvas.get("h_in"), "canvas.h_in")

    lay = spec.get("layout") or {}
    margin = _as_float(lay.get("margin_in"), "margin_in", 0.42)
    band_gap = _as_float(lay.get("band_gap_in"), "band_gap_in", 0.18)
    cell_gap = _as_float(lay.get("cell_gap_in"), "cell_gap_in", 0.14)
    inner_pad = _as_float(lay.get("inner_pad_in"), "inner_pad_in", 0.09)
    head_h = _as_float(lay.get("header_h_in"), "header_h_in", 0.62)
    foot_h = _as_float(lay.get("footer_h_in"), "footer_h_in", 0.30)

    rails = spec.get("rails") or {}
    rail_w = 0.0
    for side in ("left", "right"):
        r = rails.get(side)
        if r:
            rail_w = max(rail_w, _as_float(r.get("width_in"), "rail width", 0.40))
    rail_gap = 0.14 if rail_w else 0.0

    x0 = margin + (rail_w + rail_gap if rails.get("left") else 0.0)
    x1 = W - margin - (rail_w + rail_gap if rails.get("right") else 0.0)
    content_w = x1 - x0
    if content_w <= 1.0:
        raise ValueError("内容区宽度不足，检查 rails/margin 设置")

    has_title = bool(spec.get("title"))
    title_h = head_h if has_title else 0.10
    top = margin + title_h
    bottom = H - margin - foot_h
    avail_h = bottom - top
    if avail_h <= 1.0:
        raise ValueError("内容区高度不足，检查画布/边距设置")

    boxes: list[Box] = []
    bands = spec.get("bands") or []

    # ---- 分层模式
    if bands:
        heights = []
        for i, bd in enumerate(bands):
            h = _as_float(bd.get("height_in"), f"bands[{i}].height_in", None)
            heights.append(h if h else 1.12)
        total = sum(heights) + band_gap * (len(bands) - 1)
        if total > avail_h + 1e-6:
            k = (avail_h - band_gap * (len(bands) - 1)) / sum(heights)
            if k < 0.80:
                rep.warn(
                    f"内容高度超出可用区（需 {total:.2f}in / 有 {avail_h:.2f}in），"
                    f"已压缩到 {k*100:.0f}%；建议减少分层或减小 height_in"
                )
            heights = [h * k for h in heights]
            total = avail_h

        y = top
        for bi, bd in enumerate(bands):
            bh = heights[bi]
            band_id = bd.get("id") or bd.get("label") or f"band{bi}"
            band = Box(
                id=band_id, x=x0, y=y, w=content_w, h=bh,
                label=bd.get("label", ""), kind="band",
                tone=bd.get("tone", "muted"), radius=0.035,
            )
            boxes.append(band)

            label_col = 0.0
            if band.label:
                label_col = min(1.45, max(0.80, measure_label_w(band.label, FS["band"], 0.30)))
            gx = band.x + label_col + inner_pad
            gw = band.w - label_col - 2 * inner_pad

            groups_raw = bd.get("groups")
            if groups_raw is None:
                groups_raw = [{"items": bd.get("items", [])}]
            if not groups_raw:
                rep.err(f"分层 {band_id} 没有任何 groups/items")

            # 组宽度权重
            weights = []
            norm_groups = []
            for gi, g in enumerate(groups_raw):
                g = dict(g)
                items = [_norm_item(it, g.get("tone", "default")) for it in (g.get("items") or [])]
                g["_items"] = items
                norm_groups.append(g)
                wsum = 0.0
                for it in items:
                    wsum += max(1.0, text_w(it["label"], FS["item"]) / 72.0 + 0.55)
                if not items:
                    wsum = 1.0
                weights.append(wsum * (2.0 if g.get("span") else 1.0))

            gapt = cell_gap * (len(norm_groups) - 1)
            wsum = sum(weights) or 1.0
            gwidths = [max(0.5, (gw - gapt) * w / wsum) for w in weights]
            # 修正舍入
            diff = (gw - gapt) - sum(gwidths)
            gwidths[-1] += diff

            gxp = gx
            for gi, g in enumerate(norm_groups):
                gwd = gwidths[gi]
                glabel = g.get("label", "")
                gpad = 0.07
                ghead = 0.26 if glabel else 0.0
                grp = Box(
                    id=g.get("id") or f"{band_id}-g{gi}",
                    x=gxp, y=band.y + inner_pad * 0.8,
                    w=gwd, h=bh - inner_pad * 1.6,
                    label=glabel, kind="group",
                    tone=g.get("tone", "muted"), radius=0.04, pad=gpad,
                    parent=band_id,
                )
                boxes.append(grp)

                items = g["_items"]
                n = len(items) or 1
                iy = grp.y + ghead + (0.0 if ghead else gpad)
                ih = grp.h - ghead - (0.0 if ghead else gpad) - gpad
                igap = 0.10
                iw = (grp.w - 2 * gpad - igap * (n - 1)) / n
                for ii, it in enumerate(items):
                    ib = Box(
                        id=it.get("id") or it["label"],
                        x=grp.x + gpad + ii * (iw + igap),
                        y=iy, w=max(0.4, iw), h=max(0.30, ih),
                        label=it["label"], sub=it.get("sub", ""),
                        tone=it.get("tone", "default"),
                        shape=it.get("shape", "rounded"),
                        radius=_as_float(it.get("radius_in"), "radius_in", 0.05),
                        kind="item", parent=grp.id,
                    )
                    boxes.append(ib)
                gxp += gwd + cell_gap
            y += bh + band_gap

    # ---- 自由布局
    for i, fb in enumerate(spec.get("free") or []):
        fb = dict(fb)
        need = ("x_in", "y_in", "w_in", "h_in")
        for k in need:
            if k not in fb:
                raise ValueError(f"free[{i}] 缺少 {k}")
        boxes.append(
            Box(
                id=fb.get("id") or fb.get("label") or f"free{i}",
                x=_as_float(fb["x_in"], "x_in"), y=_as_float(fb["y_in"], "y_in"),
                w=_as_float(fb["w_in"], "w_in"), h=_as_float(fb["h_in"], "h_in"),
                label=fb.get("label", ""), sub=fb.get("sub", ""),
                tone=fb.get("tone", "default"), shape=fb.get("shape", "rounded"),
                radius=_as_float(fb.get("radius_in"), "radius_in", 0.05),
                kind="free", pad=_as_float(fb.get("pad_in"), "pad_in", 0.07),
            )
        )

    if not bands and not spec.get("free"):
        raise ValueError("规格里既没有 bands 也没有 free，无可绘制内容")

    # ---- 侧栏
    for side in ("left", "right"):
        r = rails.get(side)
        if not r:
            continue
        rx = margin if side == "left" else W - margin - rail_w
        boxes.append(
            Box(
                id=f"rail-{side}", x=rx, y=top, w=rail_w, h=bottom - top,
                label=r.get("label", ""), kind="rail",
                tone=r.get("tone", "muted"), radius=0.035,
                parent=None,
            )
        )

    # ---- 文字适配
    for b in boxes:
        if b.kind in ("band", "group", "rail"):
            continue
        fit_text(b)
        if b.overflow:
            rep.warn(f"文字放不下：'{b.label}'（已缩到 {b.pt:.1f}pt 仍超出，建议加大盒子或缩短文案）")

    # ---- 车道与避让区
    hlanes: list[float] = []
    yb = top
    for i in range(len(bands)):
        yb += heights[i] if bands else 0
        if i < len(bands) - 1:
            hlanes.append(yb + band_gap / 2)
        yb += band_gap

    leaves = [b for b in boxes if b.kind in ("item", "free")]
    rows: dict[float, list[Box]] = {}
    for b in leaves:
        rows.setdefault(round(b.cy, 1), []).append(b)
    vlanes: list[float] = []
    for arr in rows.values():
        arr.sort(key=lambda t: t.x)
        for a, bb in zip(arr, arr[1:]):
            if bb.x - a.right > 0.04:
                vlanes.append((a.right + bb.x) / 2)
    vlanes += [x0 - 0.09, x1 + 0.09]

    soft: list[Box] = []
    for b in boxes:
        if b.kind == "band" and b.label:
            lc = min(1.45, max(0.80, measure_label_w(b.label, FS["band"], 0.30)))
            soft.append(Box(id="_lc", x=b.x, y=b.y, w=lc, h=b.h, kind="soft"))
        elif b.kind == "rail":
            soft.append(Box(id="_rail", x=b.x, y=b.y, w=b.w, h=b.h, kind="soft"))

    meta = dict(W=W, H=H, margin=margin, x0=x0, x1=x1, top=top, bottom=bottom,
                content_w=content_w, title_h=title_h, foot_h=foot_h, rail_w=rail_w,
                hlanes=hlanes, vlanes=vlanes, soft=soft)
    return boxes, meta


# ---------------------------------------------------------------- 连线


def _port(b: Box, side: str, off: float = 0.0) -> tuple[float, float]:
    if b.shape == "oval":
        a, hb = b.w / 2, b.h / 2
        if side in ("top", "bottom"):
            dx = max(-a * 0.90, min(a * 0.90, off))
            dy = hb * math.sqrt(max(0.0, 1 - (dx / a) ** 2))
            return (b.cx + dx, b.cy - dy if side == "top" else b.cy + dy)
        dy = max(-hb * 0.90, min(hb * 0.90, off))
        dx = a * math.sqrt(max(0.0, 1 - (dy / hb) ** 2))
        return (b.cx - dx if side == "left" else b.cx + dx, b.cy + dy)
    if side in ("top", "bottom"):
        off = max(-(b.w / 2 - 0.12), min(b.w / 2 - 0.12, off))
        return (b.cx + off, b.y if side == "top" else b.bottom)
    off = max(-(b.h / 2 - 0.10), min(b.h / 2 - 0.10, off))
    return (b.x if side == "left" else b.right, b.cy + off)


def _outward(side: str) -> tuple[float, float]:
    return {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}[side]


def _dedupe(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-4 or abs(p[1] - out[-1][1]) > 1e-4:
            out.append(p)
    return out


def _seg_hits_rect(p, q, b: Box, shrink: float = 0.04) -> bool:
    x0, x1 = b.x + shrink, b.right - shrink
    y0, y1 = b.y + shrink, b.bottom - shrink
    if x1 <= x0 or y1 <= y0:
        return False
    if abs(p[1] - q[1]) < 1e-6:  # 水平
        yy = p[1]
        if not (y0 < yy < y1):
            return False
        lo, hi = sorted((p[0], q[0]))
        return lo < x1 and hi > x0
    if abs(p[0] - q[0]) < 1e-6:  # 垂直
        xx = p[0]
        if not (x0 < xx < x1):
            return False
        lo, hi = sorted((p[1], q[1]))
        return lo < y1 and hi > y0
    return False  # 斜线不参与障碍判定


def _candidates(src: Box, dst: Box, stub: float, hlanes, vlanes,
                fixed=None) -> list[tuple[list[tuple[float, float]], str, str]]:
    out: list[tuple[list[tuple[float, float]], str, str]] = []
    if fixed:
        pairs = [(fixed[0], fixed[1])]
        o1, o2 = fixed[2], fixed[3]
    else:
        pairs = [(a, b) for a in ("bottom", "top", "right", "left")
                 for b in ("top", "bottom", "left", "right")]
        o1 = o2 = 0.0

    for s1, s2 in pairs:
        p1, d1 = _port(src, s1, o1), _outward(s1)
        p2, d2 = _port(dst, s2, o2), _outward(s2)
        a1 = (p1[0] + d1[0] * stub, p1[1] + d1[1] * stub)
        a2 = (p2[0] + d2[0] * stub, p2[1] + d2[1] * stub)
        v1, v2 = d1[0] == 0, d2[0] == 0

        if v1 and v2:
            if abs(a1[0] - a2[0]) < 0.03:
                out.append(([p1, a1, (a1[0], a2[1]), a2, p2], s1, s2))
            else:
                if not hlanes:  # 有横向车道时优先走车道，避免横穿分层容器
                    mid = (a1[1] + a2[1]) / 2
                    out.append(([p1, a1, (a1[0], mid), (a2[0], mid), a2, p2], s1, s2))
                out.append(([p1, a1, (a1[0], a2[1]), a2, p2], s1, s2))
            for lx in vlanes:
                out.append(([p1, a1, (lx, a1[1]), (lx, a2[1]), a2, p2], s1, s2))
            for ly in hlanes:
                out.append(([p1, a1, (a1[0], ly), (a2[0], ly), a2, p2], s1, s2))
            # 先竖、再横、再竖、再横：把水平段停在指定车道上，
            # 用于"从别的线下方绕过去"这种避免交叉的走法
            lo_y, hi_y = sorted((a1[1], a2[1]))
            ys = [y for y in hlanes if lo_y + 0.04 < y < hi_y - 0.04]
            if len(ys) > 10:
                mid_y = (lo_y + hi_y) / 2
                ys = sorted(ys, key=lambda v: abs(v - mid_y))[:10]
            for lx in vlanes:
                for ly in ys:
                    out.append(
                        ([p1, a1, (a1[0], ly), (lx, ly), (lx, a2[1]), a2, p2], s1, s2)
                    )
        elif (not v1) and (not v2):
            if abs(a1[1] - a2[1]) < 0.03:
                out.append(([p1, a1, (a2[0], a1[1]), a2, p2], s1, s2))
            else:
                if not vlanes:
                    mid = (a1[0] + a2[0]) / 2
                    out.append(([p1, a1, (mid, a1[1]), (mid, a2[1]), a2, p2], s1, s2))
                out.append(([p1, a1, (a2[0], a1[1]), a2, p2], s1, s2))
            for ly in hlanes:
                out.append(([p1, a1, (a1[0], ly), (a2[0], ly), a2, p2], s1, s2))
            for lx in vlanes:
                out.append(([p1, a1, (lx, a1[1]), (lx, a2[1]), a2, p2], s1, s2))
        elif v1 and not v2:
            out.append(([p1, a1, (a1[0], a2[1]), a2, p2], s1, s2))
        else:
            out.append(([p1, a1, (a2[0], a1[1]), a2, p2], s1, s2))

    return [(_dedupe(c), s1, s2) for c, s1, s2 in out]


def _seg_conflict(p, q, r, s, tol: float = 0.05) -> bool:
    """两条轴对齐线段是否共线重叠（用于避免连线走同一条线）。"""
    if abs(p[1] - q[1]) < 1e-6 and abs(r[1] - s[1]) < 1e-6 and abs(p[1] - r[1]) < tol:
        lo1, hi1 = sorted((p[0], q[0]))
        lo2, hi2 = sorted((r[0], s[0]))
        return min(hi1, hi2) - max(lo1, lo2) > 0.05
    if abs(p[0] - q[0]) < 1e-6 and abs(r[0] - s[0]) < 1e-6 and abs(p[0] - r[0]) < tol:
        lo1, hi1 = sorted((p[1], q[1]))
        lo2, hi2 = sorted((r[1], s[1]))
        return min(hi1, hi2) - max(lo1, lo2) > 0.05
    return False


def _port_penalty(src: Box, dst: Box, s1: str, s2: str) -> float:
    """给进出边加方向先验：上下层的线走上下边，同排的线走左右边。"""
    same_row = abs(src.cy - dst.cy) < min(src.h, dst.h) * 0.8
    dx, dy = dst.cx - src.cx, dst.cy - src.cy
    if same_row:
        pref1, pref2 = ("right", "left") if dx >= 0 else ("left", "right")
        cross1, cross2 = ("left", "right") if dx >= 0 else ("right", "left")
    else:
        pref1, pref2 = ("bottom", "top") if dy > 0 else ("top", "bottom")
        cross1, cross2 = ("top", "bottom") if dy > 0 else ("bottom", "top")
    pen = 0.0
    for s, pref, cross in ((s1, pref1, cross1), (s2, pref2, cross2)):
        if s == pref:
            continue
        pen += 14.0 if s == cross else 6.0
    return pen


def _score_route(pts, hard, soft, src, dst, meta, drawn=(), s1="", s2="") -> float:
    hits = softpen = outside = overlap = cross = 0.0
    length = 0.0
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        length += abs(p[0] - q[0]) + abs(p[1] - q[1])
        for ob in hard:
            if ob is src or ob is dst:
                continue
            if _seg_hits_route(pts, i, ob):
                hits += 1
        for ob in soft:
            if _seg_hits_rect(p, q, ob, shrink=0.02):
                softpen += 1
        for (r, s) in drawn:
            if _seg_conflict(p, q, r, s):
                overlap += 1
            elif _seg_cross(p, q, r, s):
                cross += 1
        for (px, py) in (p, q):
            if px < 0.10 or px > meta["W"] - 0.10 or py < meta["top"] - 0.05 or py > meta["H"] - 0.08:
                outside += 1
    return (hits * 120.0 + outside * 30.0 + softpen * 12.0 + overlap * 8.0 + cross * 12.0
            + length * 1.0 + (len(pts) - 3) * 0.6 + _port_penalty(src, dst, s1, s2))


def _seg_cross(p, q, r, s, tol: float = 0.02) -> bool:
    """两条轴对齐线段是否垂直相交（T 字或十字），用于减少连线交叉。"""
    if abs(p[1] - q[1]) < 1e-6 and abs(r[0] - s[0]) < 1e-6:
        hx0, hx1 = sorted((p[0], q[0]))
        vy0, vy1 = sorted((r[1], s[1]))
        return hx0 + tol < r[0] < hx1 - tol and vy0 + tol < p[1] < vy1 - tol
    if abs(p[0] - q[0]) < 1e-6 and abs(r[1] - s[1]) < 1e-6:
        return _seg_cross(r, s, p, q, tol)
    return False


def _spread(values: list[float], lo: float, hi: float, gap: float) -> list[float]:
    """把一组理想坐标压进 [lo,hi]，并保证相邻间距不小于 gap。"""
    n = len(values)
    if n == 0:
        return []
    vals = sorted(min(max(v, lo), hi) for v in values)
    if n == 1:
        return vals
    if hi - lo < gap * (n - 1):  # 空间不够，均分
        step = (hi - lo) / (n - 1)
        return [lo + k * step for k in range(n)]
    for k in range(1, n):
        if vals[k] - vals[k - 1] < gap:
            vals[k] = vals[k - 1] + gap
    if vals[-1] > hi:
        vals[-1] = hi
        for k in range(n - 2, -1, -1):
            if vals[k + 1] - vals[k] < gap:
                vals[k] = vals[k + 1] - gap
    if vals[0] < lo:
        step = (hi - lo) / (n - 1)
        vals = [lo + k * step for k in range(n)]
    return vals


def _port_range(box: Box, side: str) -> tuple[float, float, float]:
    """返回某条边可用的 (下限, 上限, 中心)。椭圆按轮廓可用范围收缩。"""
    if side in ("top", "bottom"):
        if box.shape == "oval":
            half = box.w / 2 * 0.88
            return box.cx - half, box.cx + half, box.cx
        return box.x + 0.14, box.right - 0.14, box.cx
    if box.shape == "oval":
        half = box.h / 2 * 0.88
        return box.cy - half, box.cy + half, box.cy
    return box.y + 0.12, box.bottom - 0.12, box.cy


def compute_ports(flows, pre, n: int) -> tuple[list[float], list[float]]:
    """计算每条线进出边的落点偏移。

    目标端取来源中心的投影；若源、目标两条边的可用区间有交集，
    就在交集内取一个共享坐标，让这条线垂直直落，不产生小折返。
    源端优先复用目标端的落点，使两端对齐成一条直线。
    """
    src_off = [0.0] * n
    dst_off = [0.0] * n
    resolved: dict[int, float] = {}

    buckets: dict[tuple[str, str], list[tuple[int, Box, str, float]]] = {}
    for i, (fl, fid, src, dst) in enumerate(flows):
        s1, s2 = pre[i]
        vert = s2 in ("top", "bottom")
        lo1, hi1, _ = _port_range(src, s1)
        lo2, hi2, _ = _port_range(dst, s2)
        olo, ohi = max(lo1, lo2), min(hi1, hi2)
        if olo <= ohi:
            c1 = src.cx if vert else src.cy
            c2 = dst.cx if vert else dst.cy
            ideal = min(max((c1 + c2) / 2, olo), ohi)
        else:
            ideal = src.cx if vert else src.cy
        buckets.setdefault((dst.id, s2), []).append((i, dst, s2, ideal))

    for items in buckets.values():
        box, side = items[0][1], items[0][2]
        lo, hi, c = _port_range(box, side)
        if hi < lo:
            lo = hi = c
        items.sort(key=lambda t: t[3])
        for (i, _, _, _), p in zip(items, _spread([t[3] for t in items], lo, hi, 0.34)):
            resolved[i] = p
            dst_off[i] = p - c

    sbuckets: dict[tuple[str, str], list[tuple[int, Box, str, float]]] = {}
    for i, (fl, fid, src, dst) in enumerate(flows):
        s1, s2 = pre[i]
        vert = s1 in ("top", "bottom")
        lo, hi, c = _port_range(src, s1)
        p = resolved.get(i)
        if p is not None and lo <= p <= hi:
            ideal = p
        else:
            target = dst.cx if vert else dst.cy
            ideal = min(max(target, lo), hi) if hi >= lo else c
        sbuckets.setdefault((src.id, s1), []).append((i, src, s1, ideal))

    for items in sbuckets.values():
        box, side = items[0][1], items[0][2]
        lo, hi, c = _port_range(box, side)
        if hi < lo:
            lo = hi = c
        items.sort(key=lambda t: t[3])
        for (i, _, _, _), p in zip(items, _spread([t[3] for t in items], lo, hi, 0.34)):
            src_off[i] = p - c

    return src_off, dst_off


def _seg_hits_route(pts, i: int, ob: Box) -> bool:
    """折线中间段把模块外扩 0.03 判定，避免线贴着框线走；起止段按原尺寸。"""
    edge = i == 0 or i == len(pts) - 2
    return _seg_hits_rect(pts[i], pts[i + 1], ob, shrink=0.04 if edge else -0.03)


def _count_flow_conflicts(routes: list[tuple[str, list]]) -> tuple[int, int]:
    """统计不同连线之间的交叉数与共线重叠数。"""
    cross = overlap = 0
    for i in range(len(routes)):
        for j in range(i + 1, len(routes)):
            pi, pj = routes[i][1], routes[j][1]
            for a in range(len(pi) - 1):
                for b in range(len(pj) - 1):
                    if _seg_cross(pi[a], pi[a + 1], pj[b], pj[b + 1]):
                        cross += 1
                    elif _seg_conflict(pi[a], pi[a + 1], pj[b], pj[b + 1]):
                        overlap += 1
    return cross, overlap


def _count_hits(pts, hard, src, dst) -> int:
    n = 0
    for i in range(len(pts) - 1):
        for ob in hard:
            if ob is src or ob is dst:
                continue
            if _seg_hits_route(pts, i, ob):
                n += 1
    return n


def route(src: Box, dst: Box, hard, soft, meta, rep: Report, fid: str,
          fixed=None, drawn=()) -> tuple[list[tuple[float, float]], str, str]:
    # 在已画好的线上下各留一条平行车道，让新线可以"从它下面绕过去"而不是交叉
    hlanes = list(meta["hlanes"])
    vlanes = list(meta["vlanes"])
    for (r, s) in drawn:
        if abs(r[1] - s[1]) < 1e-6:
            hlanes += [r[1] - 0.09, r[1] + 0.09]
        elif abs(r[0] - s[0]) < 1e-6:
            vlanes += [r[0] - 0.09, r[0] + 0.09]
    hlanes = sorted({round(v, 2) for v in hlanes})
    vlanes = sorted({round(v, 2) for v in vlanes})

    best = None
    for pts, s1, s2 in _candidates(src, dst, 0.14, hlanes, vlanes, fixed):
        sc = _score_route(pts, hard, soft, src, dst, meta, drawn, s1, s2)
        if best is None or sc < best[0]:
            best = (sc, pts, s1, s2)

    if DEBUG:
        ranked = sorted(
            ((_score_route(p, hard, soft, src, dst, meta, drawn, a, b), p, a, b)
             for p, a, b in _candidates(src, dst, 0.14, hlanes, vlanes, fixed)),
            key=lambda t: t[0])[:4]
        for sc, p, a, b in ranked:
            print(f"    [cand] {sc:7.2f} {a}->{b} {[(round(x, 2), round(y, 2)) for x, y in p]}")
            if sc == ranked[0][0]:
                for k in range(len(p) - 1):
                    for ob in hard:
                        if ob is src or ob is dst:
                            continue
                        if _seg_hits_rect(p[k], p[k + 1], ob):
                            print(f"        hit {ob.label or ob.id} "
                                  f"({ob.x:.2f},{ob.y:.2f},{ob.w:.2f},{ob.h:.2f})"
                                  f" seg {p[k]}->{p[k+1]}")

    if best is None:
        rep.warn(f"连线 {fid} 无法路由，已跳过")
        return [], "", ""

    _, pts, s1, s2 = best
    hits = _count_hits(pts, hard, src, dst)
    if hits:
        rep.warn(f"连线 {fid} 仍然穿过 {hits} 个模块，建议调整模块位置或改用 free 手动布点")
    return pts, s1, s2


def _separate(pts, drawn, hard, src, dst, delta: float = 0.07):
    """与其他连线共线重叠时，把该段平移一点，避免两条线叠成一条。"""
    pts = list(pts)
    base = _count_hits(pts, hard, src, dst)
    for i in range(len(pts) - 1):
        if not any(_seg_conflict(pts[i], pts[i + 1], r, s) for r, s in drawn):
            continue
        vertical = abs(pts[i][0] - pts[i + 1][0]) < 1e-6
        for d in (delta, -delta, 2 * delta, -2 * delta):
            cand = list(pts)
            if vertical:
                cand[i] = (pts[i][0] + d, pts[i][1])
                cand[i + 1] = (pts[i + 1][0] + d, pts[i + 1][1])
            else:
                cand[i] = (pts[i][0], pts[i][1] + d)
                cand[i + 1] = (pts[i + 1][0], pts[i + 1][1] + d)
            if _count_hits(cand, hard, src, dst) <= base:
                pts = cand
                break
    return pts


def place_label(pts, boxes, segs, lw: float, lh: float, meta) -> tuple[float, float]:
    """沿折线搜索标签位置：不压模块、不压其他连线，优先水平段靠近中点。"""
    best = None
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        seg = abs(p[0] - q[0]) + abs(p[1] - q[1])
        if seg < 0.30:
            continue
        horiz = abs(p[1] - q[1]) < 1e-6
        steps = max(2, int(seg / 0.10))
        for k in range(1, steps):
            t = k / steps
            mx = p[0] + (q[0] - p[0]) * t
            my = p[1] + (q[1] - p[1]) * t
            if horiz:
                lx, ly = mx - lw / 2, my - lh - 0.03
            else:
                lx, ly = mx + 0.05, my - lh / 2
            probe = Box(id="_lab", x=lx, y=ly, w=lw, h=lh, kind="soft")
            pen = sum(1 for b in boxes if _overlap(probe, b, tol=0.0))
            for (r, s) in segs:
                if _seg_hits_rect(r, s, probe, shrink=0.0):
                    pen += 1
            if lx < meta["margin"] - 0.1 or lx + lw > meta["W"] - meta["margin"] + 0.1:
                pen += 2
            score = pen * 40.0 + abs(t - 0.5) * 1.2 + (0.0 if horiz else 0.6)
            if best is None or score < best[0]:
                best = (score, lx, ly)
    if best is None:
        p, q = pts[0], pts[-1]
        return ((p[0] + q[0]) / 2 - lw / 2, (p[1] + q[1]) / 2 - lh / 2)
    return best[1], best[2]


# ---------------------------------------------------------------- 绘制


def _rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h.upper())


def _set_font(run, size: float, color: str, bold: bool = False) -> None:
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = "Arial"
    f.color.rgb = _rgb(color)
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = etree.SubElement(rPr, qn("a:ea"))
    ea.set("typeface", "Microsoft YaHei")


def _shape_enum(kind: str):
    return {"rect": MSO_SHAPE.RECTANGLE, "oval": MSO_SHAPE.OVAL}.get(kind, MSO_SHAPE.ROUNDED_RECTANGLE)


def _no_shadow(shp) -> None:
    try:
        shp.shadow.inherit = False
    except Exception:
        spPr = shp._element.spPr
        if spPr.find(qn("a:effectLst")) is None:
            etree.SubElement(spPr, qn("a:effectLst"))


def draw_container(slide, b: Box, fill_key: str, line_key: str, lw: float,
                   dash: bool = False) -> None:
    shp = slide.shapes.add_shape(
        _shape_enum(b.shape), Inches(b.x), Inches(b.y), Inches(b.w), Inches(b.h)
    )
    _no_shadow(shp)
    shp.fill.solid()
    shp.fill.fore_color.rgb = _rgb(THEME[fill_key])
    shp.line.color.rgb = _rgb(THEME[line_key])
    shp.line.width = Pt(lw)
    if dash:
        shp.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    if b.shape == "rounded":
        try:
            shp.adjustments[0] = min(0.5, b.radius / max(0.01, min(b.w, b.h)))
        except Exception:
            pass
    shp.text_frame.text = ""
    return shp


def draw_box(slide, b: Box) -> None:
    fill_key, line_key, text_key, bold = TONES.get(b.tone, TONES["default"])
    text_hex = THEME[text_key]
    shp = slide.shapes.add_shape(
        _shape_enum(b.shape), Inches(b.x), Inches(b.y), Inches(b.w), Inches(b.h)
    )
    _no_shadow(shp)
    shp.fill.solid()
    shp.fill.fore_color.rgb = _rgb(THEME[fill_key])
    shp.line.color.rgb = _rgb(THEME[line_key])
    shp.line.width = Pt(LW["box"])
    if b.shape == "rounded":
        try:
            shp.adjustments[0] = min(0.5, b.radius / max(0.01, min(b.w, b.h)))
        except Exception:
            pass

    tf = shp.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.03)
    tf.margin_right = Inches(0.03)
    tf.margin_top = Inches(0.01)
    tf.margin_bottom = Inches(0.01)

    paragraphs = []
    sub_hex = "C7D6E4" if b.tone == "strong" else THEME["muted"]
    for ln in b.lines:
        paragraphs.append((ln, b.pt, text_hex, bold, 0.0))
    for ln in b.sub_lines:
        paragraphs.append((ln, b.sub_pt, sub_hex, False, 2.0))

    if not paragraphs:
        tf.text = ""
        return

    first = True
    for (txt, size, color, is_bold, space_before) in paragraphs:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = PP_ALIGN.CENTER
        p.line_spacing = 1.10
        if space_before:
            p.space_before = Pt(space_before)
        r = p.add_run()
        r.text = txt
        _set_font(r, size, color, is_bold)


def draw_text(slide, x, y, w, h, text, size, color, bold=False,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, vertical=False,
              spacing: float = 1.0) -> None:
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    if vertical:
        tf._txBody.bodyPr.set("vert", "vert270")
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    r = p.add_run()
    r.text = text
    _set_font(r, size, color, bold)
    return tb


def draw_line(slide, pts: list[tuple[float, float]], color: str, width: float,
              arrow: bool = True, dash: bool = False) -> None:
    if len(pts) < 2:
        return
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
            continue
        c = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(p[0]), Inches(p[1]), Inches(q[0]), Inches(q[1])
        )
        c.line.color.rgb = _rgb(color)
        c.line.width = Pt(width)
        if dash:
            c.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        if arrow and i == len(pts) - 2:
            ln = c.line._get_or_add_ln()
            tail = etree.SubElement(ln, qn("a:tailEnd"))
            tail.set("type", "triangle")
            tail.set("w", "med")
            tail.set("len", "med")


# ---------------------------------------------------------------- 自检


def _overlap(a: Box, b: Box, tol: float = 0.02) -> bool:
    return (
        a.x + tol < b.right and b.x + tol < a.right
        and a.y + tol < b.bottom and b.y + tol < a.bottom
    )


def check_layout(boxes: list[Box], meta: dict, rep: Report) -> None:
    leaves = [b for b in boxes if b.kind in ("item", "free")]
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            if _overlap(leaves[i], leaves[j]):
                rep.err(f"模块重叠：'{leaves[i].label or leaves[i].id}' 与 '{leaves[j].label or leaves[j].id}'")

    for b in leaves:
        if b.x < -0.01 or b.y < -0.01 or b.right > meta["W"] + 0.01 or b.bottom > meta["H"] + 0.01:
            rep.err(f"模块超出画布：'{b.label or b.id}'")
        if b.w < 0.45 or b.h < 0.28:
            rep.warn(f"模块过小（{b.w:.2f}x{b.h:.2f}in）：'{b.label or b.id}'")

    tones = {b.tone for b in leaves}
    if len(tones) > 4:
        rep.warn(f"使用了 {len(tones)} 种模块配色（{sorted(tones)}），建议不超过 3 种以免视觉失焦")


# ---------------------------------------------------------------- 组装


def build(spec: dict, out_pptx: Path | None, rep: Report, make_png: bool = False,
          width: int = 2560) -> Path | None:
    boxes, meta = layout(spec, rep)
    W, H = meta["W"], meta["H"]
    if DEBUG:
        for b in boxes:
            print(f"  [box] {b.kind:5s} {(b.id or '')[:14]:14s} "
                  f"x={b.x:6.2f} y={b.y:6.2f} w={b.w:6.2f} h={b.h:6.2f} cy={b.cy:6.2f}")
        print(f"  [lane] H={[round(v,2) for v in meta['hlanes']]}")
        print(f"  [lane] V={[round(v,2) for v in meta['vlanes']]}")

    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 背景
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(W), Inches(H))
    _no_shadow(bg)
    bg.fill.solid()
    bg.fill.fore_color.rgb = _rgb("FFFFFF")
    bg.line.fill.background()
    bg.text_frame.text = ""

    # 容器：先 band 再 group
    for b in boxes:
        if b.kind == "band":
            draw_container(slide, b, "band_fill", "band_line", LW["band"])
        elif b.kind == "group":
            draw_container(slide, b, "group_fill", "group_line", LW["group"])
        elif b.kind == "rail":
            draw_container(slide, b, "band_fill", "band_line", LW["band"], dash=True)

    # 模块
    for b in boxes:
        if b.kind in ("item", "free"):
            draw_box(slide, b)

    # 分层标签
    for b in boxes:
        if b.kind == "band" and b.label:
            label_col = min(1.45, max(0.80, measure_label_w(b.label, FS["band"], 0.30)))
            draw_text(slide, b.x + 0.04, b.y, label_col - 0.04, b.h, b.label,
                      FS["band"], THEME["muted"], bold=True, align=PP_ALIGN.CENTER)

    # 组标题
    for b in boxes:
        if b.kind == "group" and b.label:
            draw_text(slide, b.x + 0.07, b.y + 0.03, b.w - 0.14, 0.20, b.label,
                      FS["group"], THEME["faint"], bold=True, align=PP_ALIGN.LEFT,
                      anchor=MSO_ANCHOR.MIDDLE)

    # 侧栏文字
    for b in boxes:
        if b.kind == "rail" and b.label:
            draw_text(slide, b.x, b.y, b.w, b.h, b.label, FS["rail"],
                      THEME["muted"], bold=True, align=PP_ALIGN.CENTER, vertical=True)

    # 连线
    by_id: dict[str, Box] = {}
    for b in boxes:
        if b.kind in ("item", "free"):
            by_id[b.id] = b
            by_id.setdefault(b.label, b)

    hard = [b for b in boxes if b.kind in ("item", "free")]
    soft = meta["soft"]

    flows = []
    for fl in spec.get("flows") or []:
        src_id, dst_id = fl.get("from"), fl.get("to")
        fid = fl.get("id") or f"{src_id}->{dst_id}"
        if src_id not in by_id or dst_id not in by_id:
            rep.err(f"连线 {fid} 引用了不存在的模块（from={src_id!r}, to={dst_id!r}）")
            continue
        flows.append((fl, fid, by_id[src_id], by_id[dst_id]))

    # 预路由：先确定每条线从哪个边进出，再按"目标模块+边"分组错开落点
    pre: list[tuple[str, str]] = []
    for fl, fid, src, dst in flows:
        _, s1, s2 = route(src, dst, hard, soft, meta, Report(), fid)
        pre.append((s1, s2))

    src_offs, dst_offs = compute_ports(flows, pre, len(flows))

    drawn: list[tuple[tuple[float, float], tuple[float, float]]] = []
    pending_labels: list[tuple[list[tuple[float, float]], str]] = []
    flow_routes: list[tuple[str, list[tuple[float, float]]]] = []

    for i, (fl, fid, src, dst) in enumerate(flows):
        s1, s2 = pre[i]
        pts, _, _ = route(src, dst, hard, soft, meta, rep, fid,
                          fixed=(s1, s2, src_offs[i], dst_offs[i]), drawn=tuple(drawn))
        if pts and _count_hits(pts, hard, src, dst) > 0:
            alt, _, _ = route(src, dst, hard, soft, meta, Report(), fid, drawn=tuple(drawn))
            if alt and _count_hits(alt, hard, src, dst) < _count_hits(pts, hard, src, dst):
                pts = alt
        if not pts:
            continue

        pts = _separate(pts, drawn, hard, src, dst)
        if DEBUG:
            print(f"  [dbg] flow {fid}: {[(round(a, 2), round(b, 2)) for a, b in pts]}"
                  f" hits={_count_hits(pts, hard, src, dst)}")

        drawn.extend((pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        flow_routes.append((fid, pts))
        dash = str(fl.get("style", "solid")).lower() in ("dash", "dashed")
        draw_line(slide, pts, THEME.get(fl.get("color", "flow"), THEME["flow"]),
                  LW["flow"], arrow=fl.get("arrow", True), dash=dash)
        if fl.get("label"):
            pending_labels.append((pts, fl["label"]))

    # 所有连线画完后再放标签，让标签同时避开模块和其他连线
    label_obstacles = hard + [b for b in boxes if b.kind == "group"]
    for pts, lab in pending_labels:
        lw_, lh_ = 0.90, 0.17
        lx, ly = place_label(pts, label_obstacles, drawn, lw_, lh_, meta)
        probe = Box(id="_lab", x=lx, y=ly, w=lw_, h=lh_, kind="soft")
        hit = [b.label or b.id for b in hard if _overlap(probe, b, tol=0.0)]
        if hit:
            rep.warn(f"连线标签 '{lab}' 压到模块 {hit}，可加大模块间距或去掉该标签")
        draw_text(slide, lx, ly, lw_, lh_, lab, FS["flow"], THEME["muted"],
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    if len(flow_routes) > 1:
        n_cross, n_ovl = _count_flow_conflicts(flow_routes)
        if n_cross or n_ovl:
            rep.warn(f"连线之间交叉 {n_cross} 处、共线重叠 {n_ovl} 处；"
                     f"调整模块顺序或精简连线通常能消除")
        else:
            rep.ok(f"{len(flow_routes)} 条连线之间无交叉、无重叠")

    # 标题区
    if spec.get("title"):
        title_w = meta["x1"] - meta["margin"] - 0.05
        if spec.get("footer"):
            title_w -= 3.1
        draw_text(slide, meta["margin"], meta["margin"] - 0.06,
                  max(2.0, title_w), 0.40,
                  spec["title"], FS["title"], THEME["ink"], bold=True,
                  align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        sub = spec.get("subtitle")
        if sub:
            draw_text(slide, meta["margin"], meta["margin"] + 0.30,
                      meta["x1"] - meta["margin"], 0.24,
                      sub, FS["subtitle"], THEME["muted"], align=PP_ALIGN.LEFT)
        # 细分隔线
        ry = meta["top"] - 0.12
        draw_line(slide, [(meta["margin"], ry), (meta["x1"], ry)],
                  THEME["hairline"], LW["hair"], arrow=False)

    # 图例（右下）
    strip_cy = meta["bottom"] + meta["foot_h"] / 2
    legend = spec.get("legend")
    legend_w = 0.0
    if legend:
        if isinstance(legend, bool):
            legend = [
                {"label": "核心模块", "tone": "default"},
                {"label": "重点模块", "tone": "accent"},
            ]
        entries = []
        for it in legend:
            tw = text_w(it.get("label", ""), FS["legend"]) / 72.0
            entries.append((it, tw))
            legend_w += 0.16 + 0.05 + tw + 0.20
        lx = meta["x1"] - legend_w
        for it, tw in entries:
            fk, lk, _, _ = TONES.get(it.get("tone", "default"), TONES["default"])
            sw_shp = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(lx), Inches(strip_cy - 0.05),
                Inches(0.16), Inches(0.10))
            _no_shadow(sw_shp)
            sw_shp.fill.solid()
            sw_shp.fill.fore_color.rgb = _rgb(THEME[fk])
            sw_shp.line.color.rgb = _rgb(THEME[lk])
            sw_shp.line.width = Pt(0.75)
            try:
                sw_shp.adjustments[0] = 0.25
            except Exception:
                pass
            draw_text(slide, lx + 0.21, strip_cy - 0.09, tw + 0.05, 0.18,
                      it.get("label", ""), FS["legend"], THEME["muted"], align=PP_ALIGN.LEFT)
            lx += 0.16 + 0.05 + tw + 0.20

    # 假设与注释（左下）
    notes = spec.get("notes") or []
    if notes:
        txt = "；".join(notes)
        if not txt.startswith("假设"):
            txt = "假设：" + txt
        note_w = meta["content_w"] * 0.70
        if legend_w:
            note_w = min(note_w, meta["x1"] - legend_w - 0.25 - meta["margin"])
        draw_text(slide, meta["margin"], strip_cy - 0.09,
                  max(1.0, note_w), 0.18, txt, FS["note"],
                  THEME["faint"], align=PP_ALIGN.LEFT)

    if spec.get("footer"):
        draw_text(slide, meta["x1"] - 3.0, meta["margin"] - 0.06, 3.0, 0.40,
                  spec["footer"], FS["note"], THEME["faint"], align=PP_ALIGN.RIGHT)

    check_layout(boxes, meta, rep)

    if out_pptx is None:
        return None

    out_pptx.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_pptx))
    rep.ok(f"已生成 {out_pptx}")

    if make_png:
        png = export_png(out_pptx, width=width)
        if png:
            rep.ok(f"已导出 {png}")

    return out_pptx


# ---------------------------------------------------------------- PNG 导出

_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$created = $false
try { $app = [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') }
catch { $app = New-Object -ComObject PowerPoint.Application; $created = $true }
$pres = $app.Presentations.Open("__PPTX__", $true, $false, $false)
$n = $pres.Slides.Count
for ($i = 1; $i -le $n; $i++) {
    $pres.Slides.Item($i).Export("__OUT__\slide_$i.png", "PNG", __W__, __H__)
}
$pres.Close()
if ($created) { $app.Quit() }
Write-Output "EXPORT_OK $n"
"""


def _ascii_tmp() -> Path:
    """PowerPoint COM 在含中文的路径上会抛 DirectoryNotFoundException，必须用纯 ASCII 目录。"""
    base = Path(tempfile.gettempdir())
    if re.search(r"[^\x00-\x7F]", str(base)):
        base = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Windows\\Temp"
    p = base / "archbuild_png"
    p.mkdir(parents=True, exist_ok=True)
    return p


def export_png(pptx_path: Path, width: int = 2560) -> Path | None:
    pptx_path = Path(pptx_path).resolve()
    tmp = _ascii_tmp()
    for old in tmp.glob("*.png"):
        try:
            old.unlink()
        except Exception:
            pass

    # 1) 拷贝到 ASCII 路径
    tmp_pptx = tmp / "deck.pptx"
    shutil.copyfile(pptx_path, tmp_pptx)

    # 2) 计算高度
    prs = Presentation(str(pptx_path))
    ratio = prs.slide_height / prs.slide_width
    height = int(round(width * ratio / 2) * 2)

    ps1 = tmp / "export.ps1"
    script = (
        _PS_TEMPLATE
        .replace("__PPTX__", str(tmp_pptx))
        .replace("__OUT__", str(tmp))
        .replace("__W__", str(width))
        .replace("__H__", str(height))
    )
    ps1.write_text(script, encoding="utf-8-sig")

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        print("[ERROR] PowerPoint 导出超时（180s）", file=sys.stderr)
        return None

    pngs = sorted(tmp.glob("slide_*.png"), key=lambda p: int(re.findall(r"\d+", p.stem)[0]))
    if not pngs:
        msg = (proc.stderr or proc.stdout or "").strip()
        print(f"[ERROR] PNG 导出失败，请确认本机安装了 Microsoft PowerPoint。\n{msg}",
              file=sys.stderr)
        return None

    out_dir = pptx_path.parent
    if len(pngs) == 1:
        target = out_dir / (pptx_path.stem + ".png")
        shutil.copyfile(pngs[0], target)
        return target

    outs = []
    for i, p in enumerate(pngs, 1):
        t = out_dir / f"{pptx_path.stem}_{i}.png"
        shutil.copyfile(p, t)
        outs.append(t)
    return outs[0]


# ---------------------------------------------------------------- CLI


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_build(args) -> int:
    spec_path = Path(args.spec).resolve()
    spec = _load(spec_path)
    out_dir = Path(args.out).resolve() if args.out else spec_path.parent
    name = args.name or spec_path.stem
    rep = Report()
    out = out_dir / f"{name}.pptx"
    build(spec, out, rep, make_png=args.png, width=args.width)
    print(rep.dump())
    if rep.errors:
        return 2
    if args.strict and rep.warns:
        return 1
    return 0


def cmd_check(args) -> int:
    spec = _load(Path(args.spec).resolve())
    rep = Report()
    build(spec, None, rep)
    print(rep.dump())
    if rep.errors:
        return 2
    return 1 if (args.strict and rep.warns) else 0


def cmd_export(args) -> int:
    p = Path(args.pptx).resolve()
    if not p.exists():
        print(f"[ERROR] 文件不存在: {p}")
        return 2
    out = export_png(p, width=args.width)
    print(f"[OK   ] {out}" if out else "[ERROR] 导出失败")
    return 0 if out else 2


def cmd_demo(args) -> int:
    demo = Path(__file__).resolve().parent.parent / "assets" / "example-layered.json"
    spec = _load(demo)
    out_dir = Path(args.out).resolve() if args.out else Path.cwd()
    rep = Report()
    build(spec, out_dir / "示例_系统总体架构.pptx", rep, make_png=args.png, width=args.width)
    print(rep.dump())
    return 0 if not rep.errors else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="规格驱动的架构图生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="生成 pptx（可选导出 png）")
    b.add_argument("spec")
    b.add_argument("--out", help="输出目录，默认与 spec 同目录")
    b.add_argument("--name", help="输出文件名（不含扩展名）")
    b.add_argument("--png", action="store_true", help="同时导出 PNG")
    b.add_argument("--width", type=int, default=2560, help="PNG 宽度像素，默认 2560")
    b.add_argument("--strict", action="store_true", help="有 WARN 也返回非零")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check", help="只做布局自检，不写文件")
    c.add_argument("spec")
    c.add_argument("--strict", action="store_true")
    c.set_defaults(func=cmd_check)

    e = sub.add_parser("export", help="把已有 pptx 导出为 PNG")
    e.add_argument("pptx")
    e.add_argument("--out", help="（保留）输出目录")
    e.add_argument("--width", type=int, default=2560)
    e.set_defaults(func=cmd_export)

    d = sub.add_parser("demo", help="用内置示例生成一张图")
    d.add_argument("--out", help="输出目录，默认当前目录")
    d.add_argument("--png", action="store_true")
    d.add_argument("--width", type=int, default=2560)
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
