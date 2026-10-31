from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class RacePhase(Enum):
    IDLE = auto()
    LED_COUNTDOWN = auto()  # 부저 + RED LED 순차 점등
    LIGHTS_OFF = auto()  # 1~3초 후 부저 + 소등
    WAITING_START = auto()  # 랜덤 1~3초 대기
    RACING = auto()  # 출발신호 후 계측
    FINISHED = auto()


@dataclass
class Participant:
    rc_id: str
    name: str
    student_id: str
    marker_id: int

    @classmethod
    def from_dict(cls, data: dict) -> "Participant":
        rc_id = str(data.get("rc_id", "RC-00"))
        marker = data.get("marker_id")
        if marker is None:
            # RC-00 → 0, RC-01 → 1 (마커 ID 0부터)
            digits = "".join(ch for ch in rc_id if ch.isdigit())
            marker = int(digits) if digits else 0
        return cls(
            rc_id=rc_id,
            name=str(data.get("name", "")),
            student_id=str(data.get("student_id", "")),
            marker_id=int(marker),
        )


@dataclass
class RunnerResult:
    participant: Participant
    lap_times_ms: list[float] = field(default_factory=list)
    penalty_ms: float = 0.0
    false_start: bool = False
    finished: bool = False
    disqualified: bool = False  # 수동 탈락(기록말소형)

    @property
    def total_ms(self) -> Optional[float]:
        if self.disqualified or not self.lap_times_ms:
            return None
        return sum(self.lap_times_ms) + self.penalty_ms

    def format_lap(self, index: int) -> str:
        if index >= len(self.lap_times_ms):
            return "--:--:---"
        return format_ms(self.lap_times_ms[index])

    def format_total(self) -> str:
        total = self.total_ms
        if total is None:
            return "--:--:---"
        return format_ms(total)


def format_ms(ms: float) -> str:
    """MM:SS:MS (밀리초 3자리)."""
    total = max(0, int(ms))
    minutes = total // 60_000
    seconds = (total % 60_000) // 1000
    millis = total % 1000
    return f"{minutes:02d}:{seconds:02d}:{millis:03d}"


@dataclass
class RankRow:
    rank: int
    rc_id: str
    name: str
    student_id: str
    lap_labels: list[str]
    total_label: str
    penalty_ms: float = 0.0
    disqualified: bool = False
