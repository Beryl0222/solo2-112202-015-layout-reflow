"""页内几何与双栏版面判断。

box 沿用资料约定：页内 x,y,宽,高，单位为资料像素，仅供理解原始版面。
本模块只使用资料里已经给出的块和坐标，不生成任何新的图面内容。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# 双栏资料的栏间留白。左栏块最右约 x=300，右栏块最左约 x=299，
# 因此以 295 为栏分界；横跨两栏的块会同时与两个栏区相交。
GUTTER_X = 295
LEFT = "左栏"
RIGHT = "右栏"
SPANNING = "跨栏"


@dataclass(frozen=True)
class Box:
    """页内矩形（资料像素）。"""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def overlaps_x(self, left: int, right: int) -> bool:
        return self.x < right and self.right > left


def parse_box(raw: str) -> Box:
    """解析 ``x,y,宽,高`` 形式的 box 字段。"""
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"box 必须是 4 个整数：{raw!r}")
    try:
        x, y, width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"box 含非整数：{raw!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"box 宽高必须为正：{raw!r}")
    return Box(x, y, width, height)


def page_width(blocks: Iterable[dict]) -> int:
    """以本页所有块的最右沿作为页宽估计。"""
    return max(parse_box(block["box"]).right for block in blocks)


def block_column(block: dict) -> str:
    """判断块位于左栏、右栏还是横跨两栏。

    跨栏块（供应商常见的横跨两栏标题与图注）同时与左右栏区相交；
    只落在一侧的块归入对应栏，不用距离去猜测它“属于”另一侧的图。
    """
    box = parse_box(block["box"])
    in_left = box.overlaps_x(0, GUTTER_X)
    in_right = box.overlaps_x(GUTTER_X, 10**6)
    if in_left and in_right:
        return SPANNING
    if in_right:
        return RIGHT
    return LEFT
