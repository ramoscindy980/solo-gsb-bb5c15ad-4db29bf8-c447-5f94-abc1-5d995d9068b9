"""规划核心与 API 的测试。"""
from __future__ import annotations

import pytest

from app.planner import InfeasibleError, plan_pages


def test_single_page_when_everything_fits():
    res = plan_pages([100.0, 200.0, 150.0], [0.0, 0.0], 1000.0, 2.0)
    assert res["page_count"] == 1
    assert res["min_turn_rest"] is None  # 无需翻页
    assert res["pages"][0]["start_system"] == 0
    assert res["pages"][0]["end_system"] == 2
    assert res["pages"][0]["turn_rest_after"] is None
    assert res["total_slack_squared"] == pytest.approx((1000.0 - 450.0) ** 2)


def test_turn_only_at_safe_boundary():
    # 边界 0 休止不足，只能在边界 1 翻页
    res = plan_pages([5.0, 5.0, 5.0], [0.5, 5.0], 10.0, 1.0)
    assert res["page_count"] == 2
    assert (res["pages"][0]["start_system"], res["pages"][0]["end_system"]) == (0, 1)
    assert (res["pages"][1]["start_system"], res["pages"][1]["end_system"]) == (2, 2)
    assert res["pages"][0]["turn_rest_after"] == 5.0
    assert res["min_turn_rest"] == 5.0


def test_bottleneck_is_maximized():
    # 两种可行切分：[0,1]|[2]（最短休止 3）与 [0]|[1,2]（最短休止 5）→ 选后者
    res = plan_pages([5.0, 5.0, 5.0], [5.0, 3.0], 10.0, 1.0)
    assert res["min_turn_rest"] == 5.0
    assert res["pages"][0]["end_system"] == 0


def test_bottleneck_beats_slack_and_page_count():
    # 方案 A：[6]|[4,6]|[4] 最短休止 9，留白平方和 52，3 页
    # 方案 B：[6,4]|[6,4] 最短休止 4，留白平方和 0，2 页
    # 第一目标优先 → 选 A
    res = plan_pages([6.0, 4.0, 6.0, 4.0], [9.0, 4.0, 9.0], 10.0, 1.0)
    assert res["min_turn_rest"] == 9.0
    assert res["page_count"] == 3
    assert res["total_slack_squared"] == pytest.approx(52.0)


def test_slack_squares_minimized_within_bottleneck():
    # 所有边界休止均为 9，瓶颈不约束切分；[5,5]|[6,4] 留白平方和 1+1=2 最小
    res = plan_pages([5.0, 5.0, 6.0, 4.0], [9.0, 9.0, 9.0], 11.0, 1.0)
    assert res["min_turn_rest"] == 9.0
    assert res["page_count"] == 2
    assert res["total_slack_squared"] == pytest.approx(2.0)
    assert (res["pages"][0]["start_system"], res["pages"][0]["end_system"]) == (0, 1)


def test_page_count_minimized_last():
    # 同样最短休止 5、同样留白平方和时，页数更少者胜：
    # [5,5]|[5,5]（2 页，留白 0）vs [5]|[5,5]|[5]（3 页，留白 25+0+25）
    res = plan_pages([5.0, 5.0, 5.0, 5.0], [5.0, 5.0, 5.0], 10.0, 1.0)
    assert res["page_count"] == 2
    assert res["total_slack_squared"] == pytest.approx(0.0)


def test_slack_tiebreak_picks_balanced_pages():
    # 最短休止均为 5 时，[6,6]|[6,6]（留白平方和 32）优于 [6,6,6]|[6]（超高不可行）
    # 与 [6]|[6,6,6]（不可行），再对比 [6,6,6]… 均超高，故唯一可行均分。
    res = plan_pages([6.0, 6.0, 6.0, 6.0], [5.0, 5.0, 5.0], 13.0, 1.0)
    assert res["page_count"] == 2
    assert res["total_slack_squared"] == pytest.approx(2 * (13.0 - 12.0) ** 2)


def test_first_oversized_system_reported():
    with pytest.raises(InfeasibleError) as exc:
        plan_pages([5.0, 12.0, 20.0], [3.0, 3.0], 10.0, 1.0)
    assert exc.value.reason == "system_exceeds_page_height"
    assert exc.value.detail["system_index"] == 1  # 首个无法容纳的系统


def test_first_unsafe_boundary_reported():
    # 系统 1、2 无法同页（12 > 10），必须在边界 1 断开，但休止 0.2 < 1.0
    with pytest.raises(InfeasibleError) as exc:
        plan_pages([6.0, 6.0, 6.0], [8.0, 0.2], 10.0, 1.0)
    assert exc.value.reason == "unsafe_boundary"
    assert exc.value.detail["boundary_index"] == 1
    assert exc.value.detail["between_systems"] == [1, 2]
    assert exc.value.detail["rest_seconds"] == 0.2


def test_later_safe_boundary_does_not_hide_earlier_failure():
    # 边界 0 休止不足且系统 0、1 无法同页 → 首个失败在边界 0
    with pytest.raises(InfeasibleError) as exc:
        plan_pages([6.0, 6.0, 6.0], [0.2, 8.0], 10.0, 1.0)
    assert exc.value.reason == "unsafe_boundary"
    assert exc.value.detail["boundary_index"] == 0


def test_single_system_no_boundaries():
    res = plan_pages([300.0], [], 1000.0, 2.0)
    assert res["page_count"] == 1
    assert res["min_turn_rest"] is None


def test_exact_height_fit_allowed():
    res = plan_pages([10.0, 10.0], [2.0], 10.0, 2.0)
    assert res["page_count"] == 2
    assert res["min_turn_rest"] == 2.0
    assert res["total_slack_squared"] == pytest.approx(0.0)


def test_zero_min_safe_rest_allows_any_boundary():
    res = plan_pages([6.0, 6.0], [0.0], 10.0, 0.0)
    assert res["page_count"] == 2
    assert res["min_turn_rest"] == 0.0
