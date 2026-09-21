"""乐谱安全翻页动态规划核心。

支持两种谱架布局：

- single（单页模式）：谱架一次只展示一页，每次翻页都是实体翻页。
- spread（双页谱架模式）：谱架同时展示相邻的左右两页。
  * 左页 -> 右页为同一展开内的换页，边界处的休止**不做任何要求**；
  * 翻过右页进入下一展开才是**实体翻页**，该边界休止必须 >= 最低安全休止，
    且只有这些休止参与“最短翻页休止最大化”；
  * 因此 DP 状态必须包含已用页数的奇偶：
    起点左置时右页为偶数页，起点右置时右页为奇数页。

目标（按字典序依次优化）：
1. 最大化全曲最短的一次实体翻页休止（瓶颈值，越大越安全）；
2. 在达到该瓶颈的方案中，最小化各内容页留白高度的平方和；
3. 仍并列时，取页数更少的方案。

约束：
- 每页容纳连续若干系统，总高度不得超过页面可用高度，且每页至少 1 个系统；
- 实体翻页只允许发生在休止秒数 >= 最低安全休止的边界（全曲结束无需翻页）。

实现：两阶段精确 DP。
- 阶段一：widest-path DP 求最大可行瓶颈 B*，同时得到各状态可达性；
- 阶段二：仅保留休止 >= B* 的实体翻页边，做 (留白平方和, 页数) 字典序最小的 DP。

无解诊断：
- 若某系统自身高度超过页面可用高度，报告首个这样的系统（无法容纳）；
- 否则取首个任何奇偶状态都不可达的位置 u。可以证明：在所有系统都能单独
  容纳时，u < n、边界 u-1 休止不足，且进入 u 的唯一可能是一张右页
  （single 模式下每张页都是实体翻页；spread 模式下左页边无约束，
  不可能成为首个阻塞点）——因此边界 u-1 正是首个无法安全完成的
  （实体）翻页边界。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from typing import Any, Literal, Optional

_EPS = 1e-9  # 浮点比较容差

LayoutMode = Literal["single", "spread"]
SpreadStartSide = Literal["left", "right"]


@dataclass
class InfeasibleError(Exception):
    """无解诊断：首个无法容纳的系统，或首个无法安全（实体）翻页的边界。"""

    reason: str  # "system_exceeds_page_height" | "unsafe_boundary"
    detail: dict[str, Any] = field(default_factory=dict)


def plan_pages(
    system_heights: list[float],
    boundary_rests: list[float],
    page_height: float,
    min_safe_rest: float,
    layout_mode: LayoutMode = "single",
    spread_start_side: SpreadStartSide = "left",
) -> dict[str, Any]:
    """生成完整分页方案；无解时抛出 InfeasibleError，不产生任何部分方案。"""
    if layout_mode not in ("single", "spread"):
        raise ValueError("layout_mode 必须为 'single' 或 'spread'")
    if spread_start_side not in ("left", "right"):
        raise ValueError("spread_start_side 必须为 'left' 或 'right'")
    if layout_mode == "single":
        return _plan_single(system_heights, boundary_rests, page_height, min_safe_rest)
    return _plan_spread(
        system_heights, boundary_rests, page_height, min_safe_rest, spread_start_side
    )


def _check_inputs(
    system_heights: list[float],
    boundary_rests: list[float],
    page_height: float,
) -> int:
    """公共输入校验，返回系统数。"""
    n = len(system_heights)
    if n == 0:
        raise ValueError("system_heights must not be empty")
    if len(boundary_rests) != n - 1:
        raise ValueError("boundary_rests must have exactly len(system_heights) - 1 entries")
    return n


def _first_oversized_system(
    system_heights: list[float], page_height: float
) -> Optional[InfeasibleError]:
    """首个无法容纳的系统；全部可容纳时返回 None。"""
    for i, h in enumerate(system_heights):
        if h > page_height + _EPS:
            return InfeasibleError(
                reason="system_exceeds_page_height",
                detail={
                    "system_index": i,
                    "system_height": h,
                    "page_height": page_height,
                    "message": (
                        f"系统 {i} 的高度 {h} 超过页面可用高度 {page_height}，"
                        "任何页面都无法容纳该系统"
                    ),
                },
            )
    return None


def _plan_single(
    system_heights: list[float],
    boundary_rests: list[float],
    page_height: float,
    min_safe_rest: float,
) -> dict[str, Any]:
    """单页模式：每次跨页都是实体翻页（历史行为，响应字段保持兼容）。"""
    n = _check_inputs(system_heights, boundary_rests, page_height)
    err = _first_oversized_system(system_heights, page_height)
    if err is not None:
        raise err

    prefix = [0.0] * (n + 1)
    for i, h in enumerate(system_heights):
        prefix[i + 1] = prefix[i] + h

    def height(i: int, j: int) -> float:
        """系统 [i, j) 的总高度。"""
        return prefix[j] - prefix[i]

    # 阶段一：widest-path，最大化最短翻页休止；同时记录可达性
    widest = [-inf] * (n + 1)
    widest[0] = inf
    for j in range(1, n + 1):
        best = -inf
        for i in range(j - 1, -1, -1):
            if height(i, j) > page_height + _EPS:
                break  # 高度为正，i 再小只会更高
            if widest[i] == -inf:
                continue
            if j < n and boundary_rests[j - 1] < min_safe_rest - _EPS:
                break  # 该边界休止不足，对所有 i 都不可断开
            w = widest[i] if j == n else min(widest[i], boundary_rests[j - 1])
            if w > best:
                best = w
        widest[j] = best

    if widest[n] == -inf:
        # 首个不可达位置 u：因所有系统均可单独容纳，u <= n-1 且边界 u-1 休止不足
        u = next(k for k in range(1, n + 1) if widest[k] == -inf)
        b = u - 1
        raise InfeasibleError(
            reason="unsafe_boundary",
            detail={
                "boundary_index": b,
                "between_systems": [b, b + 1],
                "rest_seconds": boundary_rests[b],
                "min_safe_rest": min_safe_rest,
                "message": (
                    f"边界 {b}（系统 {b} 与系统 {b + 1} 之间）的休止 "
                    f"{boundary_rests[b]}s 低于最低安全休止 {min_safe_rest}s，"
                    "此前区间无法安全断开"
                ),
            },
        )

    bottleneck = widest[n]

    # 阶段二：只用休止 >= 瓶颈的翻页边，最小化 (留白平方和, 页数)
    dp: list[Optional[tuple[float, int]]] = [None] * (n + 1)
    parent = [-1] * (n + 1)
    dp[0] = (0.0, 0)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            h = height(i, j)
            if h > page_height + _EPS:
                break
            if dp[i] is None:
                continue
            if j < n and boundary_rests[j - 1] < bottleneck - _EPS:
                break  # 低于瓶颈的翻页边会破坏第一目标，禁用
            cand = (dp[i][0] + (page_height - h) ** 2, dp[i][1] + 1)
            if dp[j] is None or cand < dp[j]:
                dp[j] = cand
                parent[j] = i

    # 回溯切分点
    cuts: list[tuple[int, int]] = []
    j = n
    while j > 0:
        i = parent[j]
        cuts.append((i, j))
        j = i
    cuts.reverse()

    pages = []
    for idx, (i, j) in enumerate(cuts):
        h = height(i, j)
        pages.append(
            {
                "page": idx + 1,
                "start_system": i,
                "end_system": j - 1,
                "system_count": j - i,
                "used_height": round(h, 6),
                "slack": round(page_height - h, 6),
                "turn_rest_after": None if j == n else boundary_rests[j - 1],
            }
        )

    return {
        "layout_mode": "single",
        "page_count": len(pages),
        "min_turn_rest": None if bottleneck == inf else bottleneck,
        "total_slack_squared": round(dp[n][0], 6),
        "pages": pages,
    }


def _plan_spread(
    system_heights: list[float],
    boundary_rests: list[float],
    page_height: float,
    min_safe_rest: float,
    start_side: SpreadStartSide,
) -> dict[str, Any]:
    """双页谱架模式：状态 (系统位置, 已用页数奇偶) 的两阶段 DP。"""
    n = _check_inputs(system_heights, boundary_rests, page_height)
    err = _first_oversized_system(system_heights, page_height)
    if err is not None:
        raise err

    prefix = [0.0] * (n + 1)
    for i, h in enumerate(system_heights):
        prefix[i + 1] = prefix[i] + h

    def height(i: int, j: int) -> float:
        return prefix[j] - prefix[i]

    def new_page_is_right(pages_before_parity: int) -> bool:
        """已用页数奇偶为 m 时，下一张内容页是否落在谱架右侧。

        新页页码 = 已用页数 + 1：已用页数为偶则新页为奇数页。
        start_side='left' 时奇数页在左、偶数页在右；
        start_side='right' 时奇数页在右、偶数页在左。
        """
        new_page_odd = pages_before_parity == 0
        if start_side == "left":
            return not new_page_odd
        return new_page_odd

    # ---------- 阶段一：widest-path（状态含页码奇偶） ----------
    # widest[j][m]：覆盖系统 [0,j)、恰好用了奇偶为 m 的页数时，
    # 路径上最短实体翻页休止的最大值（inf 表示尚无实体翻页）。
    widest: list[list[float]] = [[-inf, -inf] for _ in range(n + 1)]
    widest[0][0] = inf
    for j in range(1, n + 1):
        # m = 到达 i 时的页数奇偶，也是新页落位前的奇偶
        for m in (0, 1):
            # 右页结束且全曲未完 => 实体翻页边；休止不足则该目标奇偶不可达
            if new_page_is_right(m) and j < n and boundary_rests[j - 1] < min_safe_rest - _EPS:
                continue
            best = -inf
            for i in range(j - 1, -1, -1):
                if height(i, j) > page_height + _EPS:
                    break  # 高度为正，i 再小只会更高
                wi = widest[i][m]
                if wi == -inf:
                    continue
                if new_page_is_right(m) and j < n:
                    w = min(wi, boundary_rests[j - 1])
                else:
                    w = wi  # 左页边（展开内换页）或全曲结束边：不检查休止
                if w > best:
                    best = w
            widest[j][1 - m] = best

    goal = max(widest[n])
    if goal == -inf:
        # 首个任何奇偶都不可达的位置 u。
        # 左页边无约束：若 (u-1, 左页前驱奇偶) 可达则 u 必可达，
        # 故唯一阻塞是右页实体翻页且边界 u-1 休止不足。
        u = next(k for k in range(1, n + 1) if max(widest[k]) == -inf)
        b = u - 1
        raise InfeasibleError(
            reason="unsafe_boundary",
            detail={
                "boundary_index": b,
                "between_systems": [b, b + 1],
                "rest_seconds": boundary_rests[b],
                "min_safe_rest": min_safe_rest,
                "layout_mode": "spread",
                "turn_side": "right",
                "message": (
                    f"实体翻页边界 {b}（右页翻过、系统 {b} 与系统 {b + 1} 之间）的休止 "
                    f"{boundary_rests[b]}s 低于最低安全休止 {min_safe_rest}s，"
                    "该次翻页无法安全完成"
                ),
            },
        )

    bottleneck = goal

    # ---------- 阶段二：实体翻页边休止 >= 瓶颈，最小化 (留白平方和, 页数) ----------
    dp: list[list[Optional[tuple[float, int]]]] = [[None, None] for _ in range(n + 1)]
    parent: list[list[Optional[tuple[int, int]]]] = [[None, None] for _ in range(n + 1)]
    dp[0][0] = (0.0, 0)
    for j in range(1, n + 1):
        for m in (0, 1):
            if new_page_is_right(m) and j < n and boundary_rests[j - 1] < bottleneck - _EPS:
                continue  # 低于瓶颈的实体翻页边禁用
            target = 1 - m
            for i in range(j - 1, -1, -1):
                h = height(i, j)
                if h > page_height + _EPS:
                    break
                if dp[i][m] is None:
                    continue
                cand = (dp[i][m][0] + (page_height - h) ** 2, dp[i][m][1] + 1)
                if dp[j][target] is None or cand < dp[j][target]:
                    dp[j][target] = cand
                    parent[j][target] = (i, m)

    # 全曲可结束在左页或右页，取字典序最优的终点奇偶
    end_m = 0 if (dp[n][1] is None or (dp[n][0] is not None and dp[n][0] < dp[n][1])) else 1

    # 回溯切分点
    cuts: list[tuple[int, int]] = []
    j, m = n, end_m
    while j > 0:
        i, pm = parent[j][m]
        cuts.append((i, j))
        j, m = i, pm
    cuts.reverse()

    pages = []
    for idx, (i, j) in enumerate(cuts):
        page_no = idx + 1
        odd_page = page_no % 2 == 1
        if start_side == "left":
            side = "left" if odd_page else "right"
        else:
            side = "right" if odd_page else "left"
        physical_turn = side == "right" and j < n
        h = height(i, j)
        pages.append(
            {
                "page": page_no,
                "side": side,
                "physical_turn_after": physical_turn,
                "start_system": i,
                "end_system": j - 1,
                "system_count": j - i,
                "used_height": round(h, 6),
                "slack": round(page_height - h, 6),
                "turn_rest_after": boundary_rests[j - 1] if physical_turn else None,
            }
        )

    return {
        "layout_mode": "spread",
        "spread_start_side": start_side,
        "page_count": len(pages),
        "min_turn_rest": None if bottleneck == inf else bottleneck,
        "total_slack_squared": round(dp[n][end_m][0], 6),
        "pages": pages,
    }
