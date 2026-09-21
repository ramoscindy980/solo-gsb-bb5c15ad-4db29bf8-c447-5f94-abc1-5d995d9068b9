"""请求 / 响应模型。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

LayoutMode = Literal["single", "spread"]
SpreadStartSide = Literal["left", "right"]


class PlanRequest(BaseModel):
    """按顺序提交的谱面数据与约束。"""

    system_heights: list[float] = Field(
        ..., min_length=1, description="按演奏顺序排列的各谱面系统高度"
    )
    boundary_rests: list[float] = Field(
        default_factory=list,
        description="相邻系统之间边界的休止秒数，长度 = 系统数 - 1",
    )
    page_height: float = Field(..., gt=0, allow_inf_nan=False, description="页面可用高度")
    min_safe_rest: float = Field(..., ge=0, allow_inf_nan=False, description="最低安全休止秒数")
    layout_mode: LayoutMode = Field(
        default="single",
        description="谱架布局：single=单页模式（默认）；spread=双页谱架模式",
    )
    spread_start_side: SpreadStartSide = Field(
        default="left",
        description="spread 模式下第 1 页所在侧（left/right）；single 模式下忽略",
    )

    @model_validator(mode="after")
    def _check_values(self) -> "PlanRequest":
        for h in self.system_heights:
            if h != h or h in (float("inf"), float("-inf")) or h <= 0:
                raise ValueError("system_heights 必须全部为正的有限数值")
        for r in self.boundary_rests:
            if r != r or r in (float("inf"), float("-inf")) or r < 0:
                raise ValueError("boundary_rests 必须全部为非负的有限数值")
        if len(self.boundary_rests) != len(self.system_heights) - 1:
            raise ValueError(
                "boundary_rests 的长度必须等于 len(system_heights) - 1"
            )
        return self


class PageOut(BaseModel):
    """单页模式的逐页标注（字段与历史版本完全一致）。"""

    # single 模式严格保持历史响应形状：spread 专有字段通过 extra 字段携带
    model_config = {"extra": "allow"}

    page: int
    start_system: int
    end_system: int
    system_count: int
    used_height: float
    slack: float
    turn_rest_after: Optional[float] = None


class PlanOut(BaseModel):
    id: int
    created_at: str
    system_heights: list[float]
    boundary_rests: list[float]
    page_height: float
    min_safe_rest: float
    layout_mode: LayoutMode
    spread_start_side: Optional[SpreadStartSide] = None
    system_count: int
    page_count: int
    min_turn_rest: Optional[float] = None
    total_slack_squared: float
    pages: list[PageOut]


class PlanSummary(BaseModel):
    id: int
    created_at: str
    system_count: int
    page_count: int
    min_turn_rest: Optional[float] = None
    total_slack_squared: float
