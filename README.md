# 乐谱安全翻页规划 API

提交按演奏顺序排列的谱面系统高度、相邻系统边界的休止秒数、页面可用高度与最低安全休止，
服务用动态规划生成**完整分页方案**：

- 每页容纳连续若干系统，总高度**不得超过页面可用高度**；
- 只允许在休止秒数 **≥ 最低安全休止**的边界完成**实体翻页**（最后一页之后无需翻页）；
- 优化目标按字典序依次进行：
  1. **最大化**全曲最短的一次实体翻页休止（瓶颈值，越大越安全）；
  2. 在达到该瓶颈的方案中，**最小化各页留白高度的平方和**；
  3. 仍并列时，**取页数更少**的方案。

支持两种谱架布局（请求参数 `layout_mode`）：

- **`single`（默认）**：谱架一次只展示一页，每次翻页都是实体翻页；
- **`spread`**：**双页谱架模式**，相邻的左页、右页同时可见。
  左页翻到右页是同一展开（spread）内的换页，**该边界休止不做任何检查**；
  只有**翻过右页**进入下一展开才是实体翻页——该边界休止必须 ≥ `min_safe_rest`，
  且只有这些休止参与“最短翻页休止最大化”。`spread_start_side` 决定第 1 页
  从谱架哪一侧开始（`left`/`right`，默认 `left`）。

无解时不保存任何部分方案，并在响应中指出**首个无法容纳的系统**或
**首个无法安全完成的（实体）翻页边界**。所有成功方案存入 SQLite，可随时查询。

## 快速启动

唯一需要的一条命令（依赖安装与建库建表均随启动自动完成）：

```bash
docker compose up --build
```

服务地址：**http://localhost:8000**

- 交互式接口文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## 配置

通过环境变量配置（`docker-compose.yml` 中已给出默认值，均可不改）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_PATH` | `/data/plans.db`（容器内） | SQLite 数据库文件路径，Compose 已挂载卷 `plans-data` 持久化 |
| `PORT` | `8000` | 服务监听端口，Compose 映射到宿主机 8000 |

## 接口

### `POST /plans` — 生成并保存分页方案

```bash
curl -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "system_heights": [120, 130, 110, 125, 115],
    "boundary_rests": [1.0, 4.0, 0.5, 6.0],
    "page_height": 300,
    "min_safe_rest": 2.0
  }'
```

- `system_heights`：按顺序排列的各谱面系统高度（正数，至少 1 个）；
- `boundary_rests`：相邻系统之间边界的休止秒数，长度 = 系统数 − 1（非负）；
- `page_height`：页面可用高度（正数）；
- `min_safe_rest`：最低安全休止秒数（非负）；
- `layout_mode`：谱架布局，`single`（单页模式，默认）或 `spread`（双页谱架模式）；
- `spread_start_side`：`spread` 模式下第 1 页所在侧，`left`（默认）或 `right`；
  `single` 模式下该参数被忽略。

### 双页谱架模式（`layout_mode: "spread"`）

谱架同时展示相邻左右两页，页码奇偶被纳入规划状态：第 1 页的侧别由
`spread_start_side` 决定，之后左右交替。

- **展开内边界（左页 → 右页）**：两页同时可见，边界处的休止**不检查**、也不计入瓶颈；
- **实体翻页边界（右页之后，且全曲尚未结束）**：休止必须 ≥ `min_safe_rest`，
  并参与最短翻页休止的最大化；
- 全曲可以结束在左页或右页，末页之后一律不翻页；
- 内容不足时允许末个展开只有一侧有内容（空出的一侧不计页数、不计留白）。

```bash
curl -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "system_heights": [120, 130, 110, 125, 115],
    "boundary_rests": [1.0, 4.0, 0.5, 6.0],
    "page_height": 300,
    "min_safe_rest": 2.0,
    "layout_mode": "spread",
    "spread_start_side": "left"
  }'
```

成功返回 `201`，逐页额外标注 `side`（`left`/`right`）与
`physical_turn_after`（该页之后是否为实体翻页）；`turn_rest_after` 仅在
实体翻页处有值（展开内换页与末页均为 `null`）：

```json
{
  "id": 2,
  "layout_mode": "spread",
  "spread_start_side": "left",
  "page_count": 3,
  "min_turn_rest": 6.0,
  "total_slack_squared": 40950.0,
  "pages": [
    {"page": 1, "side": "left",  "physical_turn_after": false, "start_system": 0, "end_system": 1, "used_height": 250.0, "slack": 50.0,  "turn_rest_after": null},
    {"page": 2, "side": "right", "physical_turn_after": true,  "start_system": 2, "end_system": 3, "used_height": 235.0, "slack": 65.0,  "turn_rest_after": 6.0},
    {"page": 3, "side": "left",  "physical_turn_after": false, "start_system": 4, "end_system": 4, "used_height": 115.0, "slack": 185.0, "turn_rest_after": null}
  ]
}
```

`single` 模式的响应与历史版本兼容：逐页对象只包含原有字段（不含
`side` / `physical_turn_after`），顶层新增 `layout_mode: "single"`，
`spread_start_side` 为 `null`。

成功返回 `201`（single 模式）：

```json
{
  "id": 1,
  "layout_mode": "single",
  "spread_start_side": null,
  "page_count": 3,
  "min_turn_rest": 4.0,
  "total_slack_squared": 40950.0,
  "pages": [
    {"page": 1, "start_system": 0, "end_system": 1, "used_height": 250.0, "slack": 50.0, "turn_rest_after": 4.0},
    {"page": 2, "start_system": 2, "end_system": 3, "used_height": 235.0, "slack": 65.0, "turn_rest_after": 6.0},
    {"page": 3, "start_system": 4, "end_system": 4, "used_height": 115.0, "slack": 185.0, "turn_rest_after": null}
  ]
}
```

`min_turn_rest` 为全曲最短**实体翻页**休止（整曲无需实体翻页时为 `null`）；
`turn_rest_after` 为该页之后实体翻页处的休止秒数（展开内换页与最后一页为 `null`）。

无解返回 `422`，指出首个问题区间，且**不保存任何部分方案**：

```json
{
  "detail": {
    "error": "no_feasible_pagination",
    "reason": "unsafe_boundary",
    "boundary_index": 1,
    "between_systems": [1, 2],
    "rest_seconds": 0.2,
    "min_safe_rest": 1.0,
    "message": "边界 1（系统 1 与系统 2 之间）的休止 0.2s 低于最低安全休止 1.0s，此前区间无法安全断开"
  }
}
```

`reason` 取值：

- `system_exceeds_page_height`：首个高度超过页面可用高度的系统（附 `system_index`），任何页面都无法容纳；
- `unsafe_boundary`：首个无法安全完成的实体翻页边界（附 `boundary_index` 与相邻系统下标）。
  `spread` 模式下额外返回 `"turn_side": "right"`，说明该边界是翻过右页的实体翻页；
  展开内左页→右页的边界不检查休止，不会成为此诊断的对象。

### `GET /plans/{id}` — 查询完整方案

```bash
curl http://localhost:8000/plans/1
```

不存在时返回 `404`。

### `GET /plans` — 列出方案摘要

```bash
curl 'http://localhost:8000/plans?limit=50&offset=0'
```

## 本地开发（可选）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试（需额外安装 `pytest` 与 `httpx`）：

```bash
python3 -m pytest tests/ -q
```

## 实现说明

- 规划核心为两阶段精确动态规划（`app/planner.py`）：
  1. widest-path DP 求最大可行瓶颈（最短实体翻页休止的最大值），同时得到各状态可达性；
  2. 仅保留休止 ≥ 瓶颈的实体翻页边，做（留白平方和, 页数）字典序最小的 DP 并回溯切分点。
- `single` 模式的状态是“系统位置”；`spread` 模式把**已用页数的奇偶**纳入状态
  `(系统位置, 页数奇偶)`：新页落在左还是右取决于起点侧别与页数奇偶，
  左页边不检查休止，仅右页边承载实体翻页约束与瓶颈权重。
- 无解诊断：先检查首个超高的系统；否则取首个任何奇偶都不可达的位置——
  可证明进入该位置的只可能是一张右页（左页边无约束），其左侧边界休止必然不足，
  即为首个无法安全完成的实体翻页边界。
- 存储使用 SQLite（`app/storage.py`），请求参数（含 `layout_mode`、
  `spread_start_side`）与结果均以 JSON 落库；只有成功生成的完整方案才会入库。
  历史版本写入的记录缺少新字段时，查询按 `single` / `left` 默认值回放。
