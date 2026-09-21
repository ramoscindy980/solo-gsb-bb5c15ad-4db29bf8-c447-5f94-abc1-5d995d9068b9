"""API 层测试：建库、提交、查询、无解诊断。"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    # 重新加载 DB 路径后重建 app
    import importlib

    import app.main as main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


GOOD_BODY = {
    "system_heights": [120.0, 130.0, 110.0, 125.0, 115.0],
    "boundary_rests": [1.0, 4.0, 0.5, 6.0],
    "page_height": 300.0,
    "min_safe_rest": 2.0,
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_plan(client):
    r = client.post("/plans", json=GOOD_BODY)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["id"] == 1
    assert plan["page_count"] >= 1
    total = sum(p["used_height"] for p in plan["pages"])
    assert total == pytest.approx(sum(GOOD_BODY["system_heights"]))
    for p in plan["pages"]:
        assert p["used_height"] <= GOOD_BODY["page_height"] + 1e-6
    for p in plan["pages"][:-1]:
        assert p["turn_rest_after"] >= GOOD_BODY["min_safe_rest"]
    assert plan["pages"][-1]["turn_rest_after"] is None

    got = client.get(f"/plans/{plan['id']}")
    assert got.status_code == 200
    assert got.json() == plan

    listed = client.get("/plans")
    assert listed.status_code == 200
    assert any(s["id"] == plan["id"] for s in listed.json())


def test_infeasible_returns_422_and_saves_nothing(client):
    bad = dict(GOOD_BODY, boundary_rests=[0.1, 0.1, 0.1, 0.1], page_height=150.0)
    r = client.post("/plans", json=bad)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "no_feasible_pagination"
    assert detail["reason"] in ("system_exceeds_page_height", "unsafe_boundary")
    assert client.get("/plans").json() == []  # 不保存部分方案


def test_oversized_system_diagnosis(client):
    body = dict(GOOD_BODY, system_heights=[100.0, 999.0, 100.0], boundary_rests=[3.0, 3.0])
    r = client.post("/plans", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["reason"] == "system_exceeds_page_height"
    assert detail["system_index"] == 1


def test_get_missing_plan_404(client):
    assert client.get("/plans/42").status_code == 404


def test_single_mode_response_shape_stays_compatible(client):
    r = client.post("/plans", json=GOOD_BODY)
    assert r.status_code == 201, r.text
    plan = r.json()
    # 顶层新增 layout_mode，single 下 spread_start_side 为 null
    assert plan["layout_mode"] == "single"
    assert plan["spread_start_side"] is None
    # 逐页对象严格保持历史键集合，不插入 spread 专有字段
    for p in plan["pages"]:
        assert set(p.keys()) == {
            "page", "start_system", "end_system", "system_count",
            "used_height", "slack", "turn_rest_after",
        }
    # 显式 single 同样兼容
    r2 = client.post("/plans", json=dict(GOOD_BODY, layout_mode="single", spread_start_side="right"))
    assert r2.status_code == 201
    plan2 = r2.json()
    assert plan2["layout_mode"] == "single"
    assert "side" not in plan2["pages"][0]


def test_spread_mode_annotations(client):
    body = dict(GOOD_BODY, layout_mode="spread", spread_start_side="left")
    r = client.post("/plans", json=body)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["layout_mode"] == "spread"
    assert plan["spread_start_side"] == "left"
    n_systems = len(GOOD_BODY["system_heights"])
    for idx, p in enumerate(plan["pages"]):
        assert p["side"] in ("left", "right")
        assert p["side"] == ("left" if (idx + 1) % 2 == 1 else "right")
        assert isinstance(p["physical_turn_after"], bool)
        expect_turn = p["side"] == "right" and p["end_system"] != n_systems - 1
        assert p["physical_turn_after"] is expect_turn
        if expect_turn:
            # 实体翻页边界休止达标并计入瓶颈
            assert p["turn_rest_after"] >= GOOD_BODY["min_safe_rest"]
        else:
            # 展开内左->右与末页之后都不是实体翻页
            assert p["turn_rest_after"] is None
    physical = [p["turn_rest_after"] for p in plan["pages"] if p["physical_turn_after"]]
    if physical:
        assert plan["min_turn_rest"] == min(physical)
    else:
        assert plan["min_turn_rest"] is None

    # GET 回放逐页标注
    got = client.get(f"/plans/{plan['id']}").json()
    assert got == plan


def test_spread_start_right_accepted(client):
    body = dict(GOOD_BODY, layout_mode="spread", spread_start_side="right")
    r = client.post("/plans", json=body)
    assert r.status_code == 201, r.text
    for idx, p in enumerate(r.json()["pages"]):
        assert p["side"] == ("right" if (idx + 1) % 2 == 1 else "left")


def test_spread_infeasible_422_diagnoses_physical_turn(client):
    # 每页至多容纳 1 个系统；start=left 时首个实体翻页边界（右页后）休止不足
    bad = dict(
        GOOD_BODY,
        system_heights=[140.0] * 5,
        boundary_rests=[5.0, 0.1, 5.0, 0.1],
        page_height=150.0,
        layout_mode="spread",
        spread_start_side="left",
    )
    r = client.post("/plans", json=bad)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "no_feasible_pagination"
    assert detail["reason"] == "unsafe_boundary"
    assert detail["turn_side"] == "right"
    assert client.get("/plans").json() == []


def test_invalid_layout_enums(client):
    r = client.post("/plans", json=dict(GOOD_BODY, layout_mode="book"))
    assert r.status_code == 422
    r = client.post("/plans", json=dict(GOOD_BODY, layout_mode="spread", spread_start_side="top"))
    assert r.status_code == 422


def test_validation_errors(client):
    # 边界数量不匹配
    r = client.post("/plans", json=dict(GOOD_BODY, boundary_rests=[1.0]))
    assert r.status_code == 422
    # 非正高度
    r = client.post("/plans", json=dict(GOOD_BODY, system_heights=[0.0, 1.0]))
    assert r.status_code == 422
    # 空系统列表
    r = client.post("/plans", json=dict(GOOD_BODY, system_heights=[], boundary_rests=[]))
    assert r.status_code == 422
