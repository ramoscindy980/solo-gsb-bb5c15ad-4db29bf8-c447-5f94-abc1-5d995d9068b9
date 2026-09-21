"""双页谱架模式（spread）规划核心测试。"""
from __future__ import annotations

import pytest

from app.planner import InfeasibleError, plan_pages


def test_spread_three_pages_left_start_sides():
    # [0]左 | [1]右(实体翻页,5s) | [2]左(末页)；展开内边界 0 休止 0.2 不检查
    res = plan_pages(
        [6.0, 6.0, 6.0], [0.2, 5.0], 10.0, 1.0,
        layout_mode="spread", spread_start_side="left",
    )
    assert res["layout_mode"] == "spread"
    assert res["spread_start_side"] == "left"
    assert res["page_count"] == 3
    assert [p["side"] for p in res["pages"]] == ["left", "right", "left"]
    assert [p["physical_turn_after"] for p in res["pages"]] == [False, True, False]
    assert [p["turn_rest_after"] for p in res["pages"]] == [None, 5.0, None]
    assert res["min_turn_rest"] == 5.0


def test_spread_right_start_makes_first_page_a_turn():
    # start=right：[0]右(实体翻页,5s) | [1]左 | [2]右(末页)；边界 1 在展开内不检查
    res = plan_pages(
        [6.0, 6.0, 6.0], [5.0, 0.2], 10.0, 1.0,
        layout_mode="spread", spread_start_side="right",
    )
    assert [p["side"] for p in res["pages"]] == ["right", "left", "right"]
    assert [p["physical_turn_after"] for p in res["pages"]] == [True, False, False]
    assert res["min_turn_rest"] == 5.0


def test_spread_in_spread_boundary_never_checked():
    # 4 个系统全部放在一个展开（左右两页）内即无需实体翻页：
    # 左页 [0,1]、右页 [2,3]，组内边界 1 的休止 0.0 不检查，全曲在右页结束也不翻页
    res = plan_pages(
        [5.0, 5.0, 5.0, 5.0], [0.0, 0.0, 0.0], 10.0, 2.0,
        layout_mode="spread", spread_start_side="left",
    )
    assert res["page_count"] == 2
    assert [p["side"] for p in res["pages"]] == ["left", "right"]
    assert not any(p["physical_turn_after"] for p in res["pages"])
    assert res["min_turn_rest"] is None  # 没有任何实体翻页


def test_spread_single_page_no_physical_turn_either_side():
    for side in ("left", "right"):
        res = plan_pages(
            [300.0], [], 1000.0, 2.0,
            layout_mode="spread", spread_start_side=side,
        )
        assert res["page_count"] == 1
        assert res["pages"][0]["side"] == side
        assert res["pages"][0]["physical_turn_after"] is False
        assert res["min_turn_rest"] is None


def test_spread_unsafe_physical_turn_reported():
    # start=left 时实体翻页只能发生在偶数页（右页）之后：
    # 系统两两不可同页 -> 边界 1 必须是实体翻页，但其休止 0.2 < 1.0
    with pytest.raises(InfeasibleError) as exc:
        plan_pages(
            [6.0, 6.0, 6.0], [5.0, 0.2], 10.0, 1.0,
            layout_mode="spread", spread_start_side="left",
        )
    assert exc.value.reason == "unsafe_boundary"
    assert exc.value.detail["boundary_index"] == 1
    assert exc.value.detail["between_systems"] == [1, 2]
    assert exc.value.detail["turn_side"] == "right"
    assert exc.value.detail["rest_seconds"] == 0.2


def test_spread_diagnosis_uses_first_blocked_physical_boundary():
    # start=right：实体翻页在奇数页之后。边界 0 安全(5)，边界 1 为左页后不检查，
    # 但边界 2 是右页后的实体翻页且休止 0.2 -> 首个失败在边界 2
    with pytest.raises(InfeasibleError) as exc:
        plan_pages(
            [6.0, 6.0, 6.0, 6.0, 6.0], [5.0, 9.0, 0.2, 9.0], 10.0, 1.0,
            layout_mode="spread", spread_start_side="right",
        )
    assert exc.value.reason == "unsafe_boundary"
    assert exc.value.detail["boundary_index"] == 2


def test_spread_start_side_changes_feasibility():
    # 同一组数据：左置时实体翻页落在边界 1(0.2) 无解；右置时落在边界 0(5.0) 有解
    with pytest.raises(InfeasibleError):
        plan_pages(
            [6.0, 6.0, 6.0], [5.0, 0.2], 10.0, 1.0,
            layout_mode="spread", spread_start_side="left",
        )
    res = plan_pages(
        [6.0, 6.0, 6.0], [5.0, 0.2], 10.0, 1.0,
        layout_mode="spread", spread_start_side="right",
    )
    assert res["page_count"] == 3
    assert res["min_turn_rest"] == 5.0


def test_spread_bottleneck_only_counts_physical_turns():
    # 左置、5 个系统（每页至多 2 个）。实体翻页发生在右页（第 2、4…页）之后。
    # [0]|[1] -> 实体翻页边界 1（3s）；[2,3]|... 组内边界不检查；
    # 规划器应最大化实体翻页瓶颈，展开内的 0.2 休止不参与瓶颈
    res = plan_pages(
        [5.0, 5.0, 5.0, 5.0, 5.0],
        [0.2, 3.0, 0.2, 9.0],
        11.0, 1.0,
        layout_mode="spread", spread_start_side="left",
    )
    physical_rests = [
        p["turn_rest_after"] for p in res["pages"] if p["physical_turn_after"]
    ]
    assert all(r is not None and r >= 1.0 for r in physical_rests)
    assert res["min_turn_rest"] == min(physical_rests)
    assert res["min_turn_rest"] >= 3.0


def test_spread_oversized_system_still_reported():
    with pytest.raises(InfeasibleError) as exc:
        plan_pages(
            [5.0, 12.0], [3.0], 10.0, 1.0,
            layout_mode="spread", spread_start_side="left",
        )
    assert exc.value.reason == "system_exceeds_page_height"
    assert exc.value.detail["system_index"] == 1


def test_spread_parity_labels_are_consistent():
    res = plan_pages(
        [3.0, 3.0, 3.0, 3.0, 3.0], [5.0, 5.0, 5.0, 5.0], 8.0, 1.0,
        layout_mode="spread", spread_start_side="left",
    )
    for idx, p in enumerate(res["pages"]):
        odd_page = (idx + 1) % 2 == 1
        assert p["side"] == ("left" if odd_page else "right")
        expect_turn = p["side"] == "right" and p["end_system"] != 4
        assert p["physical_turn_after"] is expect_turn


def test_default_arguments_remain_single_mode():
    res = plan_pages([5.0, 5.0], [2.0], 10.0, 1.0)
    assert res["layout_mode"] == "single"
    assert "side" not in res["pages"][0]
    assert "physical_turn_after" not in res["pages"][0]
