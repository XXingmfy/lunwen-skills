#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_entity_attributes.py —— 为 E-R 图中的每个核心实体各生成一张实体-属性图

版式（与 assets/标准示例图/图4.8实体-属性图.png 一致）：
  - 实体矩形居中；
  - 属性椭圆围绕实体四周排布（上、上左/上右、左/右、下左/下右、下）；
  - 实体与每个属性之间用**直线**相连（允许斜直线）；
  - 不加箭头、不加折线总线、不加阴影/颜色。

这是"横平竖直"规则的唯一例外：只有实体属性图允许斜的直线连接；
流程图、架构图、模块图、用例图、E-R 图仍必须横平竖直。

输入：specs/entity-attributes.json
{
  "chapter": 4,
  "start_number": 8,
  "entities": [
    {"name": "用户", "attributes": ["用户ID", "手机号", "昵称", "角色", "状态", "信用分", "实名状态", "创建时间"]}
  ]
}

输出（每个实体一张，编号连续）：
  figs/图4.8用户实体属性图.vsdx / .png
  figs/图4.9手机设备实体属性图.vsdx / .png
  ...

用法：
  python gen_entity_attributes.py --spec specs/entity-attributes.json --outdir figs
  python gen_entity_attributes.py --spec specs/entity-attributes.json --check
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_figures as gf  # noqa: E402


ATTR_W = 1.55
ATTR_H = 0.46
ATTR_SIZE = 9.5
ENTITY_W = 1.70
ENTITY_H = 0.72
ENTITY_SIZE = 10.5
RING_RX = 2.30
RING_RY = 1.62
EDGE_GAP = 0.15

# 圆周槽位：dx/dy 是相对环半径的比例；顺序按“上 → 上左/上右 → 左/右 → 下左/下右 → 下”
SLOTS = {
    1: [(0, -1)],
    2: [(-1, 0), (1, 0)],
    3: [(0, -1), (-1, 0), (1, 0)],
    4: [(0, -1), (-1, 0), (1, 0), (0, 1)],
    5: [(0, -1), (-0.78, -0.63), (0.78, -0.63), (-0.78, 0.63), (0.78, 0.63)],
    6: [(0, -1), (-0.78, -0.63), (0.78, -0.63), (-0.78, 0.63), (0.78, 0.63), (0, 1)],
    7: [(0, -1), (-0.78, -0.63), (0.78, -0.63), (-1, 0), (1, 0),
        (-0.78, 0.63), (0.78, 0.63)],
    8: [(0, -1), (-0.78, -0.63), (0.78, -0.63), (-1, 0), (1, 0),
        (-0.78, 0.63), (0.78, 0.63), (0, 1)],
}


def _rect_intersection(cx, cy, half_w, half_h, tx, ty):
    """从中心 (cx,cy) 指向 (tx,ty) 的射线与矩形边界的交点。"""
    dx, dy = tx - cx, ty - cy
    scale = float("inf")
    if abs(dx) > 1e-9:
        scale = min(scale, half_w / abs(dx))
    if abs(dy) > 1e-9:
        scale = min(scale, half_h / abs(dy))
    if scale == float("inf"):
        return cx, cy
    return cx + dx * scale, cy + dy * scale


def _ellipse_intersection(ax, ay, half_w, half_h, tx, ty):
    """从椭圆中心 (ax,ay) 指向 (tx,ty) 的射线与椭圆边界的交点（近实体一侧）。"""
    dx, dy = tx - ax, ty - ay
    denom = math.sqrt((dx / max(half_w, 1e-6)) ** 2 + (dy / max(half_h, 1e-6)) ** 2)
    if denom < 1e-9:
        return ax, ay
    return ax + dx / denom, ay + dy / denom


def build_spec(entity, chapter, number, margin=0.12):
    attrs = [str(a).strip() for a in entity.get("attributes", []) if str(a).strip()]
    name = str(entity.get("name", "")).strip()
    if not name:
        raise ValueError("实体缺少 name")
    if not attrs:
        raise ValueError(f"实体“{name}”没有属性")
    if len(attrs) > 8:
        raise ValueError(f"实体“{name}”有 {len(attrs)} 个属性，实体属性图最多 8 个；"
                         "请合并次要字段（明细放 4.3.3 字段表）")

    slots = SLOTS[len(attrs)]
    cx = RING_RX + ATTR_W / 2 + EDGE_GAP
    cy = RING_RY + ATTR_H / 2 + EDGE_GAP

    nodes = [{
        "id": "entity",
        "kind": "box",
        "text": name,
        "x": cx - ENTITY_W / 2,
        "y": cy - ENTITY_H / 2,
        "w": ENTITY_W,
        "h": ENTITY_H,
        "size": ENTITY_SIZE,
    }]
    edges = []
    for i, ((fx, fy), txt) in enumerate(zip(slots, attrs)):
        ax = cx + fx * RING_RX
        ay = cy + fy * RING_RY
        nid = f"a{i+1}"
        nodes.append({
            "id": nid,
            "kind": "ellipse",
            "text": txt,
            "x": ax - ATTR_W / 2,
            "y": ay - ATTR_H / 2,
            "w": ATTR_W,
            "h": ATTR_H,
            "size": ATTR_SIZE,
        })
        # 直线连接：实体矩形边界 -> 属性椭圆边界（允许斜直线）
        sx, sy = _rect_intersection(cx, cy, ENTITY_W / 2, ENTITY_H / 2, ax, ay)
        ex, ey = _ellipse_intersection(ax, ay, ATTR_W / 2, ATTR_H / 2, cx, cy)
        edges.append({
            "from": "entity",
            "to": nid,
            "direct": True,
            "points": [[round(sx, 4), round(sy, 4)], [round(ex, 4), round(ey, 4)]],
            "arrow": "none",
        })

    caption = entity.get("caption") or f"{name}实体属性图"
    return {
        "figure": f"图{chapter}.{number} {caption}",
        "type": "entity-attributes",
        "margin": margin,
        "nodes": nodes,
        "edges": edges,
        "texts": [],
    }


def main():
    ap = argparse.ArgumentParser(description="批量生成实体-属性图（中心辐射版式）")
    ap.add_argument("--spec", required=True, help="entity-attributes.json")
    ap.add_argument("--outdir", default="figs")
    ap.add_argument("--check", action="store_true", help="只校验，不启动 Visio")
    args = ap.parse_args()

    with open(args.spec, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    entities = cfg.get("entities", [])
    if not entities:
        print("[gen_entity_attributes] 配置中没有 entities")
        sys.exit(1)
    chapter = int(cfg.get("chapter", 4))
    start = int(cfg.get("start_number", 8))
    margin = float(cfg.get("margin", 0.12))

    rc = 0
    for i, ent in enumerate(entities):
        number = start + i
        try:
            spec = build_spec(ent, chapter, number, margin)
        except ValueError as ex:
            print(f"[gen_entity_attributes] 配置错误：{ex}")
            rc = 1
            continue
        problems = gf.validate(spec)
        if problems:
            rc = 1
            print(f"[gen_entity_attributes] {spec['figure']} 规格问题：")
            for p in problems:
                print("  -", p)
        if args.check:
            continue
        out_base = os.path.join(args.outdir, gf.safe_name(f"图{chapter}.{number}{ent['name']}实体属性图"))
        drawer = gf.VisioDrawer(spec)
        try:
            drawer.draw()
            drawer.save(vsdx=out_base + ".vsdx", png=out_base + ".png")
            print(f"[gen_entity_attributes] OK {spec['figure']} -> {out_base}.vsdx/.png")
        finally:
            drawer.close()
    if args.check:
        print(f"[gen_entity_attributes] 校验完成：{len(entities)} 个实体")
    sys.exit(rc)


if __name__ == "__main__":
    main()
