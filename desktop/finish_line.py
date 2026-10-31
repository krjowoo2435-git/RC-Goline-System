from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Point:
    x: float
    y: float


@dataclass
class VirtualFinishLine:
    """카메라 화면 위 클릭 2점으로 정의하는 가상 결승선."""

    points: list[Point] = field(default_factory=list)
    _prev_side: dict[int, float] = field(default_factory=dict)

    def clear(self) -> None:
        self.points.clear()
        self._prev_side.clear()

    def add_point(self, x: float, y: float) -> None:
        if len(self.points) >= 2:
            self.points.clear()
            self._prev_side.clear()
        self.points.append(Point(x, y))

    @property
    def ready(self) -> bool:
        return len(self.points) == 2

    def _side(self, x: float, y: float) -> float:
        """점 (x,y)가 직선에 대해 어느 쪽에 있는지 (부호 있는 면적)."""
        assert self.ready
        a, b = self.points
        return (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x)

    def _near_segment(self, x: float, y: float, margin: float = 40.0) -> bool:
        """결승선 분절 근처인지 (무한 직선 교차 오탐 방지)."""
        a, b = self.points
        abx, aby = b.x - a.x, b.y - a.y
        length2 = abx * abx + aby * aby
        if length2 <= 1e-6:
            return False
        t = max(0.0, min(1.0, ((x - a.x) * abx + (y - a.y) * aby) / length2))
        px, py = a.x + t * abx, a.y + t * aby
        dx, dy = x - px, y - py
        return (dx * dx + dy * dy) <= margin * margin

    def check_crossing(self, marker_id: int, cx: float, cy: float) -> bool:
        """ArUco 중심이 결승선을 가로지르면 True (한 번만)."""
        if not self.ready:
            return False
        if not self._near_segment(cx, cy):
            return False
        side = self._side(cx, cy)
        prev = self._prev_side.get(marker_id)
        self._prev_side[marker_id] = side
        if prev is None:
            return False
        # 부호가 바뀌면 교차
        return prev * side < 0
