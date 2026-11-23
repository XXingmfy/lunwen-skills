#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_figures.py —— 用本机 Visio 生成论文结构图（.vsdx 可编辑源 + .png 插图）

风格严格对齐 assets/标准示例图：白底、黑框、黑字、细线、宋体，不使用彩色与阴影。
所有连线默认做正交路由：只产生水平/垂直线段，允许 90° 折线，禁止斜线。
唯一例外：实体属性图（type=entity-attributes，edge.direct=true）用中心辐射直线，允许斜线。
--check 会校验：非实体属性图的斜线、箭头目标、流程图起止节点、开始无入边/结束无出边、
节点可达性（从开始可达、可到结束）、判断分支是否标注条件。

用法：
  # 单张
  python gen_figures.py --spec assets/figure-specs/fig4-1-overall-flow.json --out figs/图4.1系统总体设计流程图
  # 批量（spec 目录下所有 *.json）
  python gen_figures.py --spec-dir assets/figure-specs --outdir figs
  # 只检查规格、不启动 Visio
  python gen_figures.py --spec xxx.json --check

规格 JSON（坐标单位：英寸；x 向右、y 向下，原点在内容左上角）：
{
  "figure": "图4.1 系统总体设计流程图",
  "nodes": [
    {"id":"n1","kind":"roundbox","text":"开始","x":0.3,"y":0.3,"w":1.0,"h":0.55},
    {"id":"n2","kind":"box","text":"需求分析","x":1.6,"y":0.3,"w":1.0,"h":0.55}
  ],
  "edges": [
    {"from":"n1","to":"n2","from_side":"right","to_side":"left","arrow":"end"}
  ],
  "texts": [
    {"text":"注：……","x":0.3,"y":3.2,"w":6.0,"h":0.3,"size":9}
  ]
}

node.kind: box | roundbox | ellipse | diamond | actor | text | note | leaf | cylinder
edge: from/to 为 node id；points 为折线拐点（"x,y" 列表），route 为 straight/orthogonal/vh/hv；
      label 为线旁文字，label_xy 指定其中心位置，缺省放在路径中点上方。
常用可选项：dash(bool)、line_weight(float, pt)、size(字号)、bold(bool)、
      text_angle(90 表示竖排文字)、align(left/center/right)、valign(top/middle/bottom)、
      from_side/to_side(left/right/top/bottom/center)、arrow(end/both/none)。

依赖：Windows + Microsoft Visio + pywin32（pip install pywin32）。
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from office_prepare import prepare_office

FONT_NAME = "宋体"
DEFAULT_FONT_SIZE = 10.0
LINE_WEIGHT_PT = 0.75
DASH_PATTERN = 2          # Visio LinePattern: 1 solid, 2 dashed
ARROW_END = "4"           # filled triangle
FILL_ROW = 4              # VisSectionObject / visRowFill
FILL_FGND = 4             # visFillForegnd


# ---------------------------------------------------------------- spec helpers
def _rect(node):
    return (float(node.get("x", 0)), float(node.get("y", 0)),
            float(node.get("w", 1)), float(node.get("h", 0.5)))


def anchor(node, side=None, at=0.5):
    x, y, w, h = _rect(node)
    side = side or "center"
    at = min(1.0, max(0.0, float(at)))
    if side == "left":
        return (x, y + h * at)
    if side == "right":
        return (x + w, y + h * at)
    if side == "top":
        return (x + w * at, y)
    if side == "bottom":
        return (x + w * at, y + h)
    return (x + w / 2, y + h / 2)


def _infer_side(a, b):
    ax, ay, aw, ah = _rect(a)
    bx, by, bw, bh = _rect(b)
    dx = (bx + bw / 2) - (ax + aw / 2)
    dy = (by + bh / 2) - (ay + ah / 2)
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def _side_pair(a, b, from_side, to_side):
    """未显式指定边连接边时，按相对位置推断；center 也转为具体边。"""
    fs = from_side or _infer_side(a, b)
    ts = to_side or _infer_side(b, a)
    if fs == "center":
        fs = _infer_side(a, b)
    if ts == "center":
        ts = _infer_side(b, a)
    return fs, ts


def _offset(p, side, distance):
    """从锚点沿边方向向外偏移，保证折线先离开图形再转弯。"""
    if side == "left":
        return (p[0] - distance, p[1])
    if side == "right":
        return (p[0] + distance, p[1])
    if side == "top":
        return (p[0], p[1] - distance)
    return (p[0], p[1] + distance)


def _clean(points, tol=1e-6):
    out = []
    for p in points:
        p = (round(float(p[0]), 4), round(float(p[1]), 4))
        if not out or abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    return out


def _orthogonalize(points):
    """把任意折线强制转成横平竖直：斜段自动插入直角拐点。"""
    out = []
    for p in points:
        if not out:
            out.append(p)
            continue
        prev = out[-1]
        if abs(p[0] - prev[0]) > 1e-6 and abs(p[1] - prev[1]) > 1e-6:
            out.append((p[0], prev[1]))
        out.append(p)
    return _clean(out)


def _connect_orthogonal(s1, t1, fs, ts):
    """连接两个已离开图形的点，只产生水平/垂直段。"""
    horizontal1 = fs in ("left", "right")
    horizontal2 = ts in ("left", "right")
    path = [s1]
    if horizontal1 and horizontal2:
        if abs(s1[1] - t1[1]) < 1e-6:
            path.append(t1)
        else:
            mx = (s1[0] + t1[0]) / 2
            path += [(mx, s1[1]), (mx, t1[1]), t1]
    elif not horizontal1 and not horizontal2:
        if abs(s1[0] - t1[0]) < 1e-6:
            path.append(t1)
        else:
            my = (s1[1] + t1[1]) / 2
            path += [(s1[0], my), (t1[0], my), t1]
    elif horizontal1:
        dirx = 1 if fs == "right" else -1
        if (t1[0] - s1[0]) * dirx < 0:
            # 目标在源图形后方：先向外绕一小段，再折回，避免穿过源图形
            detour_x = s1[0] + dirx * 0.25
            path += [(detour_x, s1[1]), (detour_x, t1[1]), (t1[0], t1[1]), t1]
        else:
            path += [(t1[0], s1[1]), t1]
    else:
        diry = 1 if fs == "bottom" else -1
        if (t1[1] - s1[1]) * diry < 0:
            detour_y = s1[1] + diry * 0.25
            path += [(s1[0], detour_y), (t1[0], detour_y), (t1[0], t1[1]), t1]
        else:
            path += [(s1[0], t1[1]), t1]
    return path


def route_points(a, b, edge):
    """默认正交路由：所有线段只能是水平或垂直。
    例外：实体属性图（edge.direct=true）用两点直线，允许斜线。"""
    fs, ts = _side_pair(a, b, edge.get("from_side"), edge.get("to_side"))
    p1 = anchor(a, fs, edge.get("from_at", 0.5))
    p2 = anchor(b, ts, edge.get("to_at", 0.5))

    if edge.get("direct"):
        pts = edge.get("points")
        if pts:
            return _clean([(float(p[0]), float(p[1])) for p in pts])
        return [p1, p2]

    pts = edge.get("points")
    if pts:
        pts = [(float(p[0]), float(p[1])) for p in pts]
        # 显式拐点也强制直角化（规格写斜点也不会画斜线）
        return _orthogonalize([p1] + pts + [p2])

    clr = float(edge.get("clearance", 0.08))
    s1 = _offset(p1, fs, clr)
    t1 = _offset(p2, ts, clr)
    path = _connect_orthogonal(s1, t1, fs, ts)
    return _clean([p1] + path + [p2])


def polyline_midpoint(path):
    """按弧长取折线中点。"""
    segs = []
    total = 0.0
    for i in range(len(path) - 1):
        d = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        segs.append(d)
        total += d
    if total <= 0:
        return path[0]
    half = total / 2
    acc = 0.0
    for i, d in enumerate(segs):
        if acc + d >= half:
            t = (half - acc) / d if d else 0
            return (path[i][0] + (path[i + 1][0] - path[i][0]) * t,
                    path[i][1] + (path[i + 1][1] - path[i][1]) * t)
        acc += d
    return path[-1]


def text_size(text, size):
    """粗略估计文字外框（英寸），中文按 1 字宽、西文按 0.55 字宽。"""
    lines = str(text).split("\n") or [""]
    w = 0.0
    for line in lines:
        units = sum(1.0 if ord(ch) > 127 else 0.55 for ch in line)
        w = max(w, units)
    h = len(lines)
    return (max(0.25, w * size / 72.0 + 0.08),
            max(0.18, h * size / 72.0 * 1.45 + 0.06))


def content_bbox(spec):
    xs, ys = [], []
    for n in spec.get("nodes", []):
        x, y, w, h = _rect(n)
        xs += [x, x + w]
        ys += [y, y + h]
        if n.get("kind") == "actor":
            pass
    for e in spec.get("edges", []):
        by_id = {n["id"]: n for n in spec.get("nodes", [])}
        if e.get("from") in by_id and e.get("to") in by_id:
            path = route_points(by_id[e["from"]], by_id[e["to"]], e)
            for p in path:
                xs.append(p[0]); ys.append(p[1])
            if e.get("label"):
                if e.get("label_xy"):
                    lx, ly = float(e["label_xy"][0]), float(e["label_xy"][1])
                else:
                    mx, my = polyline_midpoint(path)
                    lx, ly = mx, my - 0.13
                tw, th = text_size(e["label"], float(e.get("label_size", 9)))
                xs += [lx - tw / 2, lx + tw / 2]
                ys += [ly - th / 2, ly + th / 2]
        for p in e.get("points", []) or []:
            xs.append(float(p[0])); ys.append(float(p[1]))
    for t in spec.get("texts", []):
        x, y, w, h = _rect(t)
        xs += [x, x + w]
        ys += [y, y + h]
    if not xs:
        return (0.0, 0.0, 4.0, 3.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _is_diagonal(p, q, tol=1e-4):
    return abs(p[0] - q[0]) > tol and abs(p[1] - q[1]) > tol


def validate(spec):
    problems = []
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        problems.append("节点 id 重复")
    by_id = {n.get("id"): n for n in nodes}
    for e in edges:
        if e.get("from") not in by_id:
            problems.append(f"边引用了不存在的节点: {e.get('from')}")
        if e.get("to") not in by_id:
            problems.append(f"边引用了不存在的节点: {e.get('to')}")
    for n in nodes:
        if not str(n.get("text", "")).strip() and n.get("kind") != "actor":
            problems.append(f"节点 {n.get('id')} 没有文字")
        # 文字宽度粗检：超过框宽 1.18 倍时提示（竖排文字按框高判断）
        if n.get("kind") in ("box", "roundbox", "ellipse", "diamond", "entity", "leaf") and n.get("text"):
            tw, _ = text_size(n["text"], float(n.get("size", DEFAULT_FONT_SIZE)))
            limit = float(n.get("h", 1)) if n.get("text_angle") in (90, -90, "90", "-90") else float(n.get("w", 1))
            if tw > limit * 1.18:
                problems.append(f"节点 {n.get('id')} 文字可能溢出（建议加宽或换行）: {n.get('text')}")

    gtype = spec.get("type", "")
    # 1) 连线方向规则：
    #    - 实体属性图（type=entity-attributes）：中心辐射直线，允许斜线；
    #    - 其余所有图：必须横平竖直，禁止斜线。
    for i, e in enumerate(edges):
        if e.get("from") not in by_id or e.get("to") not in by_id:
            continue
        direct = bool(e.get("direct"))
        if direct:
            if gtype != "entity-attributes":
                problems.append(
                    f"只有实体属性图允许直线斜连；{gtype or '当前图'}的连线 "
                    f"{e.get('from')}→{e.get('to')} 必须横平竖直")
            continue
        path = route_points(by_id[e["from"]], by_id[e["to"]], e)
        for j in range(len(path) - 1):
            if _is_diagonal(path[j], path[j + 1]):
                problems.append(
                    f"连线 {e.get('from')}→{e.get('to')} 存在斜线段 "
                    f"({path[j][0]},{path[j][1]})→({path[j+1][0]},{path[j+1][1]})")
        # 原始拐点也必须是直角拐点；斜点会被自动直角化，但规格本身应写干净
        raw = e.get("points")
        if raw:
            fs, ts = _side_pair(by_id[e["from"]], by_id[e["to"]],
                                e.get("from_side"), e.get("to_side"))
            seq = [anchor(by_id[e["from"]], fs, e.get("from_at", 0.5))]
            seq += [(float(p[0]), float(p[1])) for p in raw]
            seq.append(anchor(by_id[e["to"]], ts, e.get("to_at", 0.5)))
            for j in range(len(seq) - 1):
                if _is_diagonal(seq[j], seq[j + 1]):
                    problems.append(
                        f"连线 {e.get('from')}→{e.get('to')} 的 points 含斜线段，"
                        f"请改为水平/垂直拐点：({seq[j][0]},{seq[j][1]})→"
                        f"({seq[j+1][0]},{seq[j+1][1]})")
                    break

    # 实体属性图专项：连线必须是“实体→属性”的单段直线，不加箭头
    if gtype == "entity-attributes":
        for e in edges:
            if not e.get("direct"):
                problems.append(f"实体属性图连线 {e.get('from')}→{e.get('to')} 必须是直线（direct=true）")
            if e.get("arrow", "none") != "none":
                problems.append(f"实体属性图连线 {e.get('from')}→{e.get('to')} 不应带箭头")
            if len(e.get("points") or []) != 2:
                problems.append(f"实体属性图连线 {e.get('from')}→{e.get('to')} 应只有两个端点")

    has_start_end = any("开始" in str(n.get("text", "")) or "结束" in str(n.get("text", ""))
                        for n in nodes)
    has_decision = any(n.get("kind") == "diamond" for n in nodes)
    flow_like = gtype == "flow" or (has_start_end and has_decision)
    if flow_like:
        # 2) 箭头方向：流程图必须指向目标
        for e in edges:
            if e.get("arrow", "end") not in ("end", "both"):
                problems.append(f"流程图连线 {e.get('from')}→{e.get('to')} 没有目标端箭头")
        # 2b) 主流程顺序：sequence 中相邻节点必须存在同方向箭头，防止 from/to 写反
        seq = spec.get("sequence")
        if seq:
            pairs = {(e.get("from"), e.get("to")) for e in edges}
            for a, b in zip(seq, seq[1:]):
                if (a, b) not in pairs:
                    problems.append(
                        f"主流程顺序要求 {a}→{b}，但图中没有这个方向的箭头"
                        f"（检查 from/to 是否写反或漏连）")
        # 3) 起止节点
        start_ids = [n["id"] for n in nodes if "开始" in str(n.get("text", ""))]
        end_ids = [n["id"] for n in nodes if "结束" in str(n.get("text", ""))]
        if len(start_ids) != 1:
            problems.append(f"流程图应有且仅有 1 个“开始”节点，当前 {len(start_ids)} 个")
        if len(end_ids) != 1:
            problems.append(f"流程图应有且仅有 1 个“结束”节点，当前 {len(end_ids)} 个")
        if len(start_ids) == 1:
            sid = start_ids[0]
            incoming = [e for e in edges if e.get("to") == sid]
            if incoming:
                problems.append(f"“开始”节点不应有入边，当前 {len(incoming)} 条")
            # 4) 可达性：从开始节点出发应能到达所有节点
            adj = {}
            for e in edges:
                adj.setdefault(e.get("from"), []).append(e.get("to"))
            seen, stack = {sid}, [sid]
            while stack:
                cur = stack.pop()
                for nxt in adj.get(cur, []):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            unreachable = [n["id"] for n in nodes
                           if n["id"] not in seen and n.get("kind") not in ("text", "note")]
            if unreachable:
                problems.append(f"从“开始”节点无法到达：{', '.join(unreachable)}")
        if len(end_ids) == 1:
            eid = end_ids[0]
            outgoing = [e for e in edges if e.get("from") == eid]
            if outgoing:
                problems.append(f"“结束”节点不应有出边，当前 {len(outgoing)} 条")
            # 反向可达性：每个处理节点都必须能走到“结束”
            radj = {}
            for e in edges:
                radj.setdefault(e.get("to"), []).append(e.get("from"))
            rseen, stack = {eid}, [eid]
            while stack:
                cur = stack.pop()
                for prev in radj.get(cur, []):
                    if prev not in rseen:
                        rseen.add(prev)
                        stack.append(prev)
            dead = [n["id"] for n in nodes
                    if n["id"] not in rseen and n.get("kind") not in ("text", "note")]
            if dead:
                problems.append(f"以下节点无法沿箭头到达“结束”：{', '.join(dead)}")
        # 5) 判断框：多个分支必须标“是/否”等标签
        for n in nodes:
            if n.get("kind") != "diamond":
                continue
            outs = [e for e in edges if e.get("from") == n["id"]]
            if len(outs) >= 2:
                unlabeled = [e for e in outs if not str(e.get("label", "")).strip()]
                if unlabeled:
                    problems.append(f"判断框“{n.get('text')}”有 {len(unlabeled)} 条分支未标注条件")
    return problems


# ---------------------------------------------------------------- Visio layer
class VisioDrawer:
    @staticmethod
    def _open_visio(client):
        """Visio 的 COM 实例偶尔会处于半退出状态，重试并校验关键接口。"""
        last = None
        for attempt in range(3):
            try:
                app = client.DispatchEx("Visio.Application")
                _ = app.Version
                _ = app.Documents.Count
                return app
            except Exception as ex:
                last = ex
                time.sleep(1.5 * (attempt + 1))
        raise last

    def __init__(self, spec):
        import win32com.client  # 延迟导入，--check 模式不需要
        self.win32 = win32com.client
        self.spec = spec
        self.visio = self._open_visio(win32com.client)
        try:
            self.visio.Visible = False
        except Exception:
            # 某些 Visio 状态下 Visible 暂时只读；不影响后台生成
            pass
        try:
            self.visio.AlertResponse = 7
        except Exception:
            pass
        self.doc = self.visio.Documents.Add("")
        self.page = self.doc.Pages.Item(1)
        self.by_id = {n["id"]: n for n in spec.get("nodes", [])}
        self.edge_labels = []

        margin = float(spec.get("margin", 0.22))
        x0, y0, x1, y1 = content_bbox(spec)
        raw_w, raw_h = x1 - x0, y1 - y0
        self.min_x, self.min_y = x0, y0
        self.page_w = max(float(spec.get("page_width", 0) or 0), raw_w + 2 * margin)
        self.page_h = max(float(spec.get("page_height", 0) or 0), raw_h + 2 * margin)
        self.margin = margin
        self.page.PageSheet.CellsU("PageWidth").FormulaU = f"{self.page_w:.3f} in"
        self.page.PageSheet.CellsU("PageHeight").FormulaU = f"{self.page_h:.3f} in"
        try:
            self.page.PageSheet.CellsU("PageDrawSizeType").FormulaU = "1"
        except Exception:
            pass

    # coordinate transform: input y-down -> Visio y-up
    def tx(self, x):
        return float(x) - self.min_x + self.margin

    def ty(self, y):
        return self.page_h - (float(y) - self.min_y + self.margin)

    # ---------- low-level style ----------
    @staticmethod
    def _set(sh, cell, val):
        try:
            sh.CellsU(cell).FormulaU = val
        except Exception:
            # 个别 Visio 版本缺少可选单元格，不影响主流程
            pass

    def _style_shape(self, sh, node):
        line_w = float(node.get("line_weight", LINE_WEIGHT_PT))
        self._set(sh, "LineColor", "RGB(0,0,0)")
        self._set(sh, "LineWeight", f"{line_w} pt")
        self._set(sh, "LinePattern", "0" if node.get("no_line") else ("2" if node.get("dash") else "1"))
        # 用 CellsSRC 写填充色：部分 Visio 版本 CellsU("FillForegroundColor") 会报错
        try:
            fill = node.get("fill", "white")
            sh.CellsSRC(1, FILL_ROW, FILL_FGND).FormulaU = "RGB(255,255,255)" if fill == "white" else "RGB(255,255,255)"
            self._set(sh, "FillPattern", "0" if fill == "none" else "1")
        except Exception:
            pass
        self._set(sh, "Para.HorzAlign", {"left": "0", "center": "1", "right": "2"}.get(node.get("align", "center"), "1"))
        self._set(sh, "VerticalAlign", {"top": "0", "middle": "1", "bottom": "2"}.get(node.get("valign", "middle"), "1"))
        size = float(node.get("size", DEFAULT_FONT_SIZE))
        self._set(sh, "Char.Font", f'"{node.get("font", FONT_NAME)}"')
        self._set(sh, "Char.Size", f"{size} pt")
        self._set(sh, "Char.Color", "RGB(0,0,0)")
        self._set(sh, "Char.Style", "1" if node.get("bold") else "0")
        self._set(sh, "LeftMargin", "0.03 in")
        self._set(sh, "RightMargin", "0.03 in")
        self._set(sh, "TopMargin", "0.01 in")
        self._set(sh, "BottomMargin", "0.01 in")
        if node.get("text_angle"):
            self._set(sh, "TxtAngle", f"{float(node['text_angle'])} deg")

    def _text_shape(self, text, x, y, w, h, node=None):
        node = dict(node or {})
        # 文字框不填充：避免白底把连线切断；标签位置应在规格里避开连线
        node.setdefault("fill", "none")
        node.setdefault("no_line", True)
        sh = self.page.DrawRectangle(self.tx(x), self.ty(y + h), self.tx(x + w), self.ty(y))
        sh.Text = str(text)
        self._style_shape(sh, node)
        return sh

    def _draw_node(self, n):
        kind = n.get("kind", "box")
        x, y, w, h = _rect(n)
        x1, y1 = self.tx(x), self.ty(y + h)
        x2, y2 = self.tx(x + w), self.ty(y)
        text = n.get("text", "")
        if kind == "actor":
            self._draw_actor(n)
            return
        if kind == "text" or kind == "note":
            self._text_shape(text, x, y, w, h, n)
            return
        if kind == "ellipse":
            sh = self.page.DrawOval(x1, y1, x2, y2)
        elif kind == "diamond":
            cx, cy = (x + w / 2, y + h / 2)
            pts = [(cx, y), (x + w, cy), (cx, y + h), (x, cy), (cx, y)]
            flat = []
            for px, py in pts:
                flat += [self.tx(px), self.ty(py)]
            sh = self.page.DrawPolyline(flat, 0)
        elif kind == "cylinder":
            sh = self._draw_cylinder(n)
        else:
            sh = self.page.DrawRectangle(x1, y1, x2, y2)
            if kind == "roundbox":
                self._set(sh, "Rounding", f"{min(w, h) * 0.16:.3f} in")
        sh.Text = str(text)
        self._style_shape(sh, n)
        if kind == "diamond":
            # 菱形文字保持水平（DrawPolyline 默认即可），不收窄边距
            pass
        return sh

    def _draw_cylinder(self, n):
        x, y, w, h = _rect(n)
        # 上下椭圆 + 两侧竖线 + 中间矩形，组合成数据库圆柱
        eh = min(h * 0.22, 0.22)
        top = self.page.DrawOval(self.tx(x), self.ty(y + eh), self.tx(x + w), self.ty(y))
        body = self.page.DrawRectangle(self.tx(x), self.ty(y + h - eh), self.tx(x + w), self.ty(y + eh))
        bot = self.page.DrawOval(self.tx(x), self.ty(y + h), self.tx(x + w), self.ty(y + h - eh))
        for sh in (top, body, bot):
            self._style_shape(sh, n)
        top.Text = str(n.get("text", ""))
        return top

    def _draw_actor(self, n):
        x, y, w, h = _rect(n)
        label = n.get("label", n.get("text", ""))
        label_h = max(0.24, float(n.get("label_size", DEFAULT_FONT_SIZE)) / 72 * 1.6)
        fig_h = h - label_h
        cx = x + w / 2
        head_r = min(w * 0.19, fig_h * 0.13)
        head_top = y + fig_h * 0.06
        head_bot = head_top + 2 * head_r
        head = self.page.DrawOval(self.tx(cx - head_r), self.ty(head_bot), self.tx(cx + head_r), self.ty(head_top))
        head_style = {"fill": "white", "line_weight": n.get("line_weight", LINE_WEIGHT_PT)}
        self._style_shape(head, head_style)
        body_bot = y + fig_h * 0.60
        arm_y = y + fig_h * 0.34
        leg_bot = y + fig_h * 0.96
        lines = [
            (cx, head_bot, cx, body_bot),
            (cx - w * 0.40, arm_y, cx + w * 0.40, arm_y),
            (cx, body_bot, cx - w * 0.34, leg_bot),
            (cx, body_bot, cx + w * 0.34, leg_bot),
        ]
        for lx1, ly1, lx2, ly2 in lines:
            sh = self.page.DrawLine(self.tx(lx1), self.ty(ly1), self.tx(lx2), self.ty(ly2))
            self._set(sh, "LineColor", "RGB(0,0,0)")
            self._set(sh, "LineWeight", f"{float(n.get('line_weight', LINE_WEIGHT_PT))} pt")
        self._text_shape(label, x, y + fig_h, w, label_h,
                         {"size": n.get("label_size", DEFAULT_FONT_SIZE), "fill": "none", "no_line": True})

    def _draw_edge(self, e):
        a, b = self.by_id[e["from"]], self.by_id[e["to"]]
        path = route_points(a, b, e)
        flat = []
        for px, py in path:
            flat += [self.tx(px), self.ty(py)]
        sh = self.page.DrawPolyline(flat, 0)
        self._set(sh, "LineColor", "RGB(0,0,0)")
        self._set(sh, "LineWeight", f"{float(e.get('line_weight', LINE_WEIGHT_PT))} pt")
        self._set(sh, "LinePattern", "2" if e.get("dash") else "1")
        arrow = e.get("arrow", "end")
        self._set(sh, "EndArrow", ARROW_END if arrow in ("end", "both") else "0")
        self._set(sh, "BeginArrow", ARROW_END if arrow == "both" else "0")
        self._set(sh, "EndArrowSize", str(int(e.get("arrow_size", 2))))
        self._set(sh, "BeginArrowSize", str(int(e.get("arrow_size", 2))))
        label = e.get("label")
        if label:
            if e.get("label_xy"):
                lx, ly = float(e["label_xy"][0]), float(e["label_xy"][1])
            else:
                mx, my = polyline_midpoint(path)
                lx, ly = mx, my - 0.13
            self.edge_labels.append((label, lx, ly, float(e.get("label_size", 9))))

    def draw(self):
        # 先线后框，保证框线压住连线端点
        for e in self.spec.get("edges", []):
            self._draw_edge(e)
        for n in self.spec.get("nodes", []):
            self._draw_node(n)
        # 连线标签最后画，避免被节点/框体遮住
        for label, lx, ly, size in self.edge_labels:
            tw, th = text_size(label, size)
            self._text_shape(label, lx - tw / 2, ly - th / 2, tw, th,
                             {"size": size, "fill": "none", "no_line": True,
                              "align": "center", "valign": "middle"})
        for t in self.spec.get("texts", []):
            x, y, w, h = _rect(t)
            self._text_shape(t.get("text", ""), x, y, w, h, t)

    def save(self, vsdx=None, png=None):
        if vsdx:
            os.makedirs(os.path.dirname(os.path.abspath(vsdx)) or ".", exist_ok=True)
            if os.path.exists(vsdx):
                os.remove(vsdx)
            self.doc.SaveAs(os.path.abspath(vsdx))
        if png:
            os.makedirs(os.path.dirname(os.path.abspath(png)) or ".", exist_ok=True)
            if os.path.exists(png):
                os.remove(png)
            self.page.Export(os.path.abspath(png))

    def close(self):
        try:
            self.doc.Close()
        finally:
            try:
                self.visio.Quit()
            except Exception:
                pass


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|]+', "_", str(s)).strip()
    s = s.replace(" ", "").replace("\u3000", "")
    return s or "figure"


def run_one(spec_path, out_base, check=False, want_vsdx=True, want_png=True):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    problems = validate(spec)
    if problems:
        print(f"[gen_figures] {os.path.basename(spec_path)} 规格问题：")
        for p in problems:
            print("  -", p)
    if check:
        return 0 if not problems else 1
    # Visio 与 Word 一样会用默认打印机做版面度量，提前隔离网络打印机。
    with prepare_office():
        return _draw_one(spec, out_base, want_vsdx, want_png)


def _draw_one(spec, out_base, want_vsdx, want_png):
    drawer = VisioDrawer(spec)
    try:
        drawer.draw()
        vsdx = out_base + ".vsdx" if want_vsdx else None
        png = out_base + ".png" if want_png else None
        drawer.save(vsdx=vsdx, png=png)
        print(f"[gen_figures] OK {spec.get('figure', '')} -> {out_base}.vsdx/.png")
        return 0
    finally:
        drawer.close()


def main():
    ap = argparse.ArgumentParser(description="Visio 论文结构图生成器")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", help="单个规格 JSON")
    src.add_argument("--spec-dir", help="规格目录（批量）")
    ap.add_argument("--out", help="单张输出基名（不含扩展名）")
    ap.add_argument("--outdir", default="figs", help="批量输出目录")
    ap.add_argument("--check", action="store_true", help="只校验规格，不启动 Visio")
    ap.add_argument("--no-vsdx", action="store_true")
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args()

    if args.spec:
        base = args.out or os.path.splitext(os.path.basename(args.spec))[0]
        sys.exit(run_one(args.spec, base, args.check, not args.no_vsdx, not args.no_png))

    files = sorted(glob.glob(os.path.join(args.spec_dir, "*.json")))
    if not files:
        print(f"[gen_figures] {args.spec_dir} 下没有 JSON 规格")
        sys.exit(1)
    rc = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            spec = json.load(f)
        if "entities" in spec:
            print(f"[gen_figures] 跳过 {os.path.basename(fp)}：实体属性图请用 "
                  "gen_entity_attributes.py 生成")
            continue
        name = spec.get("output") or spec.get("figure") or os.path.splitext(os.path.basename(fp))[0]
        base = os.path.join(args.outdir, safe_name(name))
        rc |= run_one(fp, base, args.check, not args.no_vsdx, not args.no_png)
    sys.exit(rc)


if __name__ == "__main__":
    main()
