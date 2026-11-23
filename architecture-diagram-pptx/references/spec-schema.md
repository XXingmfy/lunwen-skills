# 规格字段参考

一份规格就是一个 JSON 对象。所有长度单位是英寸（in），所有角度省略，所有字段除 `bands`/`free` 二选一外都可省略。

## 顶层

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `title` | string | — | 图标题，19pt 粗体，左上角 |
| `subtitle` | string | — | 副标题，9.5pt，标题下方 |
| `footer` | string | — | 右上角小字，如"内部资料 · 仅用于架构评审" |
| `canvas` | string \| object | `"16:9"` | `16:9` / `4:3` / `a4l` / `a4p`，或 `{"w_in":13.333,"h_in":7.5}` |
| `layout` | object | 见下 | 间距覆盖 |
| `rails` | object | — | 左右竖栏 |
| `bands` | array | — | 分层（与 `free` 至少给一个） |
| `free` | array | — | 绝对定位模块 |
| `flows` | array | `[]` | 连线 |
| `legend` | true \| array | — | 图例；`true` 用默认两项 |
| `notes` | array | `[]` | 左下角注释，多项用"；"连接，自动加"假设："前缀 |

### layout

| 字段 | 默认 | 说明 |
|---|---|---|
| `margin_in` | 0.42 | 画布外边距 |
| `band_gap_in` | 0.18 | 层间距，同时决定横向走线车道位置 |
| `cell_gap_in` | 0.14 | 同层内分组间距 |
| `inner_pad_in` | 0.09 | 层内边距 |
| `header_h_in` | 0.62 | 标题区高度（无标题时只用 0.10） |
| `footer_h_in` | 0.30 | 底部注释/图例条高度 |

## rails

```json
"rails": {
  "left":  { "label": "标准规范体系", "width_in": 0.40, "tone": "muted" },
  "right": { "label": "安全保障体系" }
}
```

竖排文字（自下而上），高度铺满内容区。`width_in` 取左右两侧的最大值，默认 0.40。适合放横切关注点，不要放具体模块。

## bands

```json
{ "id": "app", "label": "应用层", "height_in": 1.12, "tone": "muted",
  "groups": [ { "label": "业务应用", "tone": "muted", "span": false,
                "items": [ { "id": "biz", "label": "事项办理", "sub": "核心链路" } ] } ] }
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | string | label 或 `band{i}` | 连线引用用 |
| `label` | string | — | 层名，左侧标签列，留空则不留标签列 |
| `height_in` | number | 1.12 | 层高；总和超出可用区会等比压缩并告警 |
| `tone` | string | `muted` | 层底色 |
| `groups` | array | — | 分组；省略时用 `items` 直接铺满整层 |
| `items` | array | — | 无分组时的模块列表（等价于一个无标题分组） |

### groups

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | string | `{band}-g{i}` | |
| `label` | string | — | 分组标题，留空则不留标题行 |
| `tone` | string | `muted` | 分组容器配色 |
| `span` | bool | false | 宽度权重 ×2，用于需要更宽的分组 |
| `items` | array | — | 模块列表，同一分组内横向等分 |

分组宽度按组内模块的"文字长度权重"分配，不是平均分——模块多的组自动更宽。想让某组明显更宽，用 `span` 或减少其他组的模块数。

### items

```json
{ "id": "biz", "label": "事项办理", "sub": "Spring Boot", "tone": "accent",
  "shape": "rounded", "radius_in": 0.05 }
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | string | label | 连线引用；缺省时用 `label` 也能连 |
| `label` | string | 必填 | 主文字。字符串简写形式 `"事项办理"` 等价于 `{"label":"事项办理"}` |
| `sub` | string | — | 第二行小字，8.5pt 灰 |
| `tone` | string | `default` | 见配色表 |
| `shape` | string | `rounded` | `rounded` / `rect` / `oval` |
| `radius_in` | number | 0.05 | 圆角半径，仅 `rounded` 有效 |

## free

```json
{ "id": "hub", "label": "数据中台", "x_in": 5.3, "y_in": 3.0, "w_in": 2.7, "h_in": 1.4,
  "shape": "oval", "tone": "strong", "sub": "统一出口", "pad_in": 0.07 }
```

`x_in`/`y_in`/`w_in`/`h_in` 必填，坐标是画布绝对坐标（左上角原点），不受 `margin_in` 影响。其余字段同 items。

`free` 和 `bands` 可以同时使用：`bands` 负责主体分层，`free` 负责跨层或层外的特殊模块。

## flows

```json
{ "from": "portal", "to": "biz", "label": "HTTPS", "style": "dash", "arrow": true }
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `from` / `to` | string | 必填 | item 的 `id` 或 `label`；找不到会报 ERROR 并列出可选值 |
| `label` | string | — | 线上文字，8pt，自动搜索不压模块、不压其他线的位置 |
| `style` | string | `solid` | `dash` 画虚线，表示异步、可选、间接依赖 |
| `arrow` | bool | true | 末端三角箭头 |
| `color` | string | `flow` | 目前只支持主题色名 `flow` |
| `id` | string | `from->to` | 仅用于告警信息定位 |

布线规则（自动，无需配置）：

1. **避免交叉是第一优先。** 新线布线时会在已有连线的上下（或左右）各 0.09in 处生成平行车道，因此可以从别的线下方绕过去，而不是横切过去。交叉的代价远高于绕行距离，但绕行距离本身仍然计费——不会为了零交叉绕半张图。
2. 上下层的线走上下边，同排的线走左右边；反向进出会被扣分。
3. 落点取对端模块中心的投影。两端可用区间有交集时取共享坐标，让线**垂直直落**，不产生小折返——这是汇聚线好看的关键。
4. 多条线汇聚到同一模块的同一条边时，按最小间距 0.34in 错开，且顺序与来源位置一致。
5. 中间段优先走层间空隙和模块间隙构成的车道，不贴模块边框。
6. 与其他线共线重叠时平移 0.07in 让开，保持平行。
7. 椭圆模块的端点落在椭圆轮廓上，不是外接矩形。
8. 走不通时退化为最长可用路径，并输出 `WARN`——这时候应该改结构，不是改坐标。

构建结束会报告 `连线之间无交叉、无重叠` 或 `交叉 N 处、共线重叠 M 处`。理想值是 0；不是 0 时优先调整模块顺序或精简 `flows`，而不是继续调坐标。

## legend

```json
"legend": [ { "label": "重点业务模块", "tone": "accent" }, { "label": "外部系统", "tone": "ghost" } ]
```

右下角，色块 + 文字。`"legend": true` 生成默认两项（一般模块 / 重点模块）。用了非 `default` 的 tone 就应该配图例。

## notes

```json
"notes": ["支撑层与数据层为逻辑分层，物理部署可合并"]
```

左下角 8pt 灰字，自动加"假设："前缀（已以"假设"开头则不重复加）。用来声明推断项、口径、版本。**任何不是用户明确给出的结构判断，都应该写进这里。**

## 校验与报错

构建时按顺序检查，输出到 stdout：

- `[ERROR]` 模块重叠、模块超出画布、`flows` 引用不存在的模块、分层为空。必须修。
- `[WARN ]` 文字缩到下限仍放不下、连线仍穿过模块、连线标签压到模块、配色超过 4 种、内容高度被压缩到 80% 以下。
- `[INFO ]` 生成的文件路径。

`check` 子命令跑同样的检查但不写文件，改规格时用它快速迭代。
