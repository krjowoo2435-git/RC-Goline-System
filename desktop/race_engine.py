from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .hardware import HardwareController
from .models import Participant, RacePhase, RankRow, RunnerResult
from .storage import (
    append_race_results,
    force_update_record,
    mark_record_erased,
    participant_by_marker,
)

StatusCallback = Callable[[str], None]
PhaseCallback = Callable[[RacePhase], None]
RankCallback = Callable[[list[RankRow]], None]


@dataclass
class RaceConfig:
    lap_count: int = 1
    led_hold_min_s: float = 1.0
    led_hold_max_s: float = 3.0
    start_delay_min_s: float = 1.0
    start_delay_max_s: float = 3.0
    false_start_penalty_ms: float = 3000.0
    max_runners: int = 3
    # 결승선 통과 후 해당 RC-ID 재기록 중단 (역주행/정체 중복 방지)
    pass_cooldown_s: float = 7.0
    # 초음파 랩/부정출발 계측 (기본 OFF — 가상 결승선만 쓸 때)
    ultrasonic_enabled: bool = False


@dataclass
class RaceEngine:
    participants: list[Participant]
    hardware: HardwareController
    config: RaceConfig = field(default_factory=RaceConfig)
    on_status: Optional[StatusCallback] = None
    on_phase: Optional[PhaseCallback] = None
    on_rank: Optional[RankCallback] = None

    phase: RacePhase = field(default=RacePhase.IDLE, init=False)
    results: dict[str, RunnerResult] = field(default_factory=dict, init=False)
    start_monotonic: Optional[float] = field(default=None, init=False)
    _worker: Optional[threading.Thread] = field(default=None, init=False)
    _stop: bool = field(default=False, init=False)
    _finish_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _marker_to_rc: dict[int, str] = field(default_factory=dict, init=False)
    _pending_markers: dict[int, float] = field(default_factory=dict, init=False)
    _pass_cooldown_until: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.hardware.on_pass = self._on_ultrasonic_pass
        self._rebuild_marker_map()

    def _rebuild_marker_map(self) -> None:
        self._marker_to_rc = {p.marker_id: p.rc_id for p in self.participants}

    def set_participants(self, participants: list[Participant]) -> None:
        with self._lock:
            self.participants = participants
            self._rebuild_marker_map()

    def set_lap_count(self, laps: int) -> None:
        self.config.lap_count = max(1, min(10, int(laps)))

    def set_ultrasonic_enabled(self, enabled: bool) -> None:
        self.config.ultrasonic_enabled = bool(enabled)
        state = "ON" if self.config.ultrasonic_enabled else "OFF"
        self._emit_status(f"초음파 계측: {state}")

    def _emit_status(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)

    def _set_phase(self, phase: RacePhase) -> None:
        self.phase = phase
        if self.on_phase:
            self.on_phase(phase)

    def _publish_ranks(self) -> None:
        if self.on_rank:
            self.on_rank(self.ranked_rows())

    def ranked_rows(self) -> list[RankRow]:
        with self._lock:
            active = [r for r in self.results.values() if not r.disqualified]
            finished = [r for r in active if r.total_ms is not None]
            finished.sort(key=lambda r: r.total_ms or float("inf"))
            rows: list[RankRow] = []
            for i, r in enumerate(finished[: self.config.max_runners], start=1):
                rows.append(
                    RankRow(
                        rank=i,
                        rc_id=r.participant.rc_id,
                        name=r.participant.name,
                        student_id=r.participant.student_id,
                        lap_labels=[
                            r.format_lap(j) for j in range(self.config.lap_count)
                        ],
                        total_label=r.format_total(),
                        penalty_ms=r.penalty_ms,
                    )
                )
            # 미완주자
            for r in active:
                if r.total_ms is not None:
                    continue
                rows.append(
                    RankRow(
                        rank=0,
                        rc_id=r.participant.rc_id,
                        name=r.participant.name,
                        student_id=r.participant.student_id,
                        lap_labels=[
                            r.format_lap(j) for j in range(self.config.lap_count)
                        ],
                        total_label=r.format_total(),
                        penalty_ms=r.penalty_ms,
                    )
                )
            # 탈락(기록말소) 표시
            for r in self.results.values():
                if not r.disqualified:
                    continue
                rows.append(
                    RankRow(
                        rank=0,
                        rc_id=r.participant.rc_id,
                        name=r.participant.name,
                        student_id=r.participant.student_id,
                        lap_labels=["DQ"] * self.config.lap_count,
                        total_label="DQ",
                        penalty_ms=0.0,
                        disqualified=True,
                    )
                )
            return rows

    def list_penalty_targets(self) -> list[tuple[str, str]]:
        """(rc_id, display_label) — 수동 패널티 대상.

        항상 전체 참가자를 반환한다. (results에 일부만 있어도 다른 선수가 목록에서
        사라지지 않도록 — 탈락/패널티 후 다른 선수에게 부과 가능)
        """
        with self._lock:
            out: list[tuple[str, str]] = []
            for p in self.participants:
                r = self.results.get(p.rc_id)
                dq = bool(r and r.disqualified)
                label = f"{p.rc_id} | {p.name} ({p.student_id})"
                if dq:
                    label += " [DQ]"
                out.append((p.rc_id, label))
            return out

    def add_manual_penalty(self, rc_id: str, seconds: float) -> bool:
        """수동 시간 추가 (초). 종료 후에는 로컬 기록도 강제 갱신."""
        if seconds <= 0:
            self._emit_status("패널티 시간은 0보다 커야 합니다.")
            return False
        persist_row: Optional[RankRow] = None
        with self._lock:
            result = self.results.get(rc_id)
            if result is None:
                p = next((x for x in self.participants if x.rc_id == rc_id), None)
                if p is None:
                    self._emit_status(f"대상을 찾을 수 없습니다: {rc_id}")
                    return False
                result = RunnerResult(participant=p)
                self.results[rc_id] = result
            if result.disqualified:
                self._emit_status(f"{result.participant.name}은(는) 이미 탈락 상태입니다.")
                return False
            add_ms = seconds * 1000.0
            result.penalty_ms += add_ms
            name = result.participant.name
            total_penalty = result.penalty_ms
            # 종료 후·완주 기록이 있으면 저장 대상 구성 (lock 밖에서 I/O)
            if self.phase == RacePhase.FINISHED and result.total_ms is not None:
                persist_row = RankRow(
                    rank=1,
                    rc_id=result.participant.rc_id,
                    name=result.participant.name,
                    student_id=result.participant.student_id,
                    lap_labels=[
                        result.format_lap(j) for j in range(self.config.lap_count)
                    ],
                    total_label=result.format_total(),
                    penalty_ms=result.penalty_ms,
                )
        self._emit_status(
            f"수동 패널티: {name}(+{seconds:g}초) → 누적 패널티 {total_penalty / 1000:g}초"
        )
        if persist_row is not None:
            try:
                force_update_record(persist_row)
                self._emit_status(
                    f"종료 후 패널티 로컬 반영: {persist_row.name} {persist_row.total_label} "
                    "(웹 반영은 [web에 기록 업로드])"
                )
            except Exception as exc:  # noqa: BLE001
                self._emit_status(f"패널티는 적용됐으나 로컬 저장 실패: {exc}")
        self._publish_ranks()
        return True

    def disqualify(self, rc_id: str) -> bool:
        """탈락(기록말소형) — 랩/패널티 기록 삭제 + 전체기록에 말소 저장."""
        with self._lock:
            result = self.results.get(rc_id)
            if result is None:
                p = next((x for x in self.participants if x.rc_id == rc_id), None)
                if p is None:
                    self._emit_status(f"대상을 찾을 수 없습니다: {rc_id}")
                    return False
                result = RunnerResult(participant=p)
                self.results[rc_id] = result
            result.disqualified = True
            result.lap_times_ms.clear()
            result.penalty_ms = 0.0
            result.finished = False
            result.false_start = False
            name = result.participant.name
            student_id = result.participant.student_id
        try:
            mark_record_erased(student_id, name, rc_id=rc_id)
            self._emit_status(
                f"탈락(기록말소): {name} ({student_id}) — 로컬 저장됨. "
                "웹 반영은 [web에 기록 업로드]"
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_status(f"탈락 처리됨이나 로컬 저장 실패: {exc}")
        self._publish_ranks()
        return True

    def _join_worker(self, timeout: float = 2.0) -> None:
        """이전 경기 워커가 남아 있으면 종료될 때까지 대기."""
        worker = self._worker
        if worker is not None and worker.is_alive():
            if threading.current_thread() is not worker:
                worker.join(timeout=timeout)
        if worker is not None and not worker.is_alive():
            self._worker = None

    def start_race(self, lap_count: int | None = None) -> None:
        if self.phase not in (RacePhase.IDLE, RacePhase.FINISHED):
            self._emit_status("이미 경기가 진행 중입니다.")
            return
        if not self.participants:
            self._emit_status("참가자가 없습니다. participants.json을 확인하세요.")
            return

        # 중단 직후 재시작: 이전 워커가 살아 있으면 카운트다운/부저가 겹침
        self._stop = True
        self._join_worker()

        if lap_count is not None:
            self.set_lap_count(lap_count)

        target_laps = self.config.lap_count
        max_n = max(1, int(self.config.max_runners))
        registered = self.participants[:max_n]
        skipped = len(self.participants) - len(registered)

        self._stop = False
        self.hardware.reset_triggers()
        with self._lock:
            self.results = {
                p.rc_id: RunnerResult(participant=p) for p in registered
            }
            self._pending_markers.clear()
            self._pass_cooldown_until.clear()
            self.start_monotonic = None

        msg = (
            f"경기 준비 — 목표 {target_laps}랩 / 참가 {len(self.results)}명 "
            f"/ 통과 후 {self.config.pass_cooldown_s:.0f}초 재기록 금지"
        )
        if skipped > 0:
            msg += f" (레인 초과 {skipped}명 제외, 최대 {max_n}명)"
        self._emit_status(msg)
        self._publish_ranks()
        self._worker = threading.Thread(target=self._run_sequence, daemon=True)
        self._worker.start()

    def abort(self) -> None:
        self._stop = True
        self.hardware.all_leds_off()
        self._join_worker()
        self._set_phase(RacePhase.IDLE)
        self._emit_status("경기가 중단되었습니다.")

    def _sleep(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._stop:
                return False
            time.sleep(0.05)
        return True

    def _run_sequence(self) -> None:
        # 1) 부저 + RED LED 순차 점등
        self._set_phase(RacePhase.LED_COUNTDOWN)
        self._emit_status("준비: 부저 + RED LED 순차 점등")
        self.hardware.buzz(0.2)
        for i in range(3):
            if self._stop:
                return
            self.hardware.sequential_led_on(i)
            self.hardware.buzz(0.15)
            if not self._sleep(0.45):
                return

        # 2) 1~3초 후 부저 + 소등
        hold = random.uniform(self.config.led_hold_min_s, self.config.led_hold_max_s)
        self._set_phase(RacePhase.LIGHTS_OFF)
        self._emit_status(f"소등 대기 {hold:.1f}초")
        if not self._sleep(hold):
            return
        self.hardware.buzz(0.3)
        self.hardware.all_leds_off()

        # 3) 랜덤 1~3초 후 출발신호
        delay = random.uniform(
            self.config.start_delay_min_s, self.config.start_delay_max_s
        )
        self._set_phase(RacePhase.WAITING_START)
        self._emit_status(f"출발신호 대기 {delay:.1f}초 (부정출발 감시)")
        if not self._sleep(delay):
            return

        self.start_monotonic = time.monotonic()
        self._set_phase(RacePhase.RACING)
        self.hardware.buzz(0.5)
        if self.config.ultrasonic_enabled:
            self._emit_status("출발! 가상결승선·초음파·카메라 계측 중")
        else:
            self._emit_status("출발! 가상결승선·카메라 계측 중 (초음파 OFF)")

        # 경기 종료는 랩 완료 / 수동 종료로 처리
        while not self._stop and self.phase == RacePhase.RACING:
            if self._all_finished():
                self._finish()
                return
            time.sleep(0.05)

    def _all_finished(self) -> bool:
        with self._lock:
            active = [r for r in self.results.values() if not r.disqualified]
            # 전원 탈락이면 계측 대상이 없으므로 종료
            if not active:
                return bool(self.results)
            return all(len(r.lap_times_ms) >= self.config.lap_count for r in active)

    def _finish(self) -> None:
        with self._finish_lock:
            if self.phase == RacePhase.FINISHED:
                return
            self._set_phase(RacePhase.FINISHED)
        # 완주자 + 말소(DQ) 모두 저장 대상
        rows = [
            r
            for r in self.ranked_rows()
            if (r.rank > 0 and not r.disqualified) or r.disqualified
        ]
        overall_count = 0
        accepted = 0
        skipped = 0
        save_error = ""
        if rows:
            try:
                overall, accepted, skipped = append_race_results(rows)
                overall_count = len(overall)
            except Exception as exc:  # noqa: BLE001
                save_error = str(exc)
        self._publish_ranks()
        if save_error:
            self._emit_status(f"게임 종료 — 로컬 저장 실패: {save_error}")
        elif not rows:
            self._emit_status("게임 종료 — 완주 기록이 없어 로컬 저장을 건너뛰었습니다.")
        else:
            self._emit_status(
                f"게임 종료 — 순위 확정 (갱신/신규 {accepted}, 미갱신 {skipped}, 전체 {overall_count}건). "
                "학번+이름 기준 · 전기록보다 좋지 않으면 미갱신. "
                "필요 시 [web에 기록 업로드]를 누르세요."
            )

    def force_finish(self) -> None:
        if self.phase == RacePhase.RACING:
            self._finish()

    def _on_ultrasonic_pass(self, sensor_index: int, _distance: float) -> None:
        if not self.config.ultrasonic_enabled:
            return
        now = time.monotonic()
        phase = self.phase

        # 부정출발: 출발신호 전 통과
        if phase in (RacePhase.LED_COUNTDOWN, RacePhase.LIGHTS_OFF, RacePhase.WAITING_START):
            self._apply_false_start_penalty(sensor_index)
            return

        if phase != RacePhase.RACING or self.start_monotonic is None:
            return

        elapsed_ms = (now - self.start_monotonic) * 1000.0
        with self._lock:
            # 기본: 센서 인덱스 = 레인(참가자) 인덱스
            ordered = list(self.results.values())
            target: Optional[RunnerResult] = None
            if sensor_index < len(ordered):
                target = ordered[sensor_index]

            # ArUco 재매핑: 최근 2초 내 마커가 "하나뿐"일 때만 (다른 차 오기록 방지)
            recent = [
                (mid, ts)
                for mid, ts in self._pending_markers.items()
                if now - ts < 2.0
            ]
            if len(recent) == 1:
                marker_id, _ = recent[0]
                rc_id = self._marker_to_rc.get(marker_id)
                if rc_id and rc_id in self.results:
                    target = self.results[rc_id]
                    self._pending_markers.pop(marker_id, None)

            if target is None:
                return
            self._record_lap_locked(target, elapsed_ms, now, source="초음파")

        self._publish_ranks()

    def _false_start_seconds_label(self) -> str:
        sec = self.config.false_start_penalty_ms / 1000.0
        return f"{sec:g}"

    def _apply_false_start_penalty(self, sensor_index: int) -> None:
        with self._lock:
            # 해당 레인 센서 인덱스와 참가자 인덱스 대응 (0,1,2)
            participants = list(self.results.values())
            if sensor_index >= len(participants):
                return
            result = participants[sensor_index]
            if result.false_start:
                return
            result.false_start = True
            result.penalty_ms += self.config.false_start_penalty_ms
            name = result.participant.name
        self._emit_status(
            f"부정출발: {name} +{self._false_start_seconds_label()}초 패널티"
        )
        self._publish_ranks()

    def on_marker_seen(self, marker_id: int) -> None:
        """카메라 ArUco 인식 → 참가자 대응."""
        if self.phase != RacePhase.RACING:
            return
        rc_id = self._resolve_rc(marker_id)
        if not rc_id:
            return
        with self._lock:
            self._pending_markers[marker_id] = time.monotonic()
            if rc_id not in self.results and len(self.results) < self.config.max_runners:
                p = next((x for x in self.participants if x.rc_id == rc_id), None)
                if p:
                    self.results[rc_id] = RunnerResult(participant=p)

    def _resolve_rc(self, marker_id: int) -> Optional[str]:
        rc_id = self._marker_to_rc.get(marker_id)
        if rc_id:
            return rc_id
        p = participant_by_marker(self.participants, marker_id)
        return p.rc_id if p else None

    def record_finish_line_pass(self, marker_id: int) -> None:
        """가상 결승선을 ArUco 중심이 통과했을 때 랩 기록."""
        now = time.monotonic()
        if self.phase in (
            RacePhase.LED_COUNTDOWN,
            RacePhase.LIGHTS_OFF,
            RacePhase.WAITING_START,
        ):
            # 부정출발: 마커 통과
            rc_id = self._resolve_rc(marker_id)
            if not rc_id:
                return
            with self._lock:
                if rc_id not in self.results:
                    return
                result = self.results[rc_id]
                if result.false_start:
                    return
                result.false_start = True
                result.penalty_ms += self.config.false_start_penalty_ms
                name = result.participant.name
            self._emit_status(
                f"부정출발: {name} +{self._false_start_seconds_label()}초 패널티"
            )
            self._publish_ranks()
            return

        if self.phase != RacePhase.RACING or self.start_monotonic is None:
            return

        rc_id = self._resolve_rc(marker_id)
        if not rc_id:
            return

        elapsed_ms = (now - self.start_monotonic) * 1000.0
        with self._lock:
            if rc_id not in self.results:
                p = next((x for x in self.participants if x.rc_id == rc_id), None)
                if not p or len(self.results) >= self.config.max_runners:
                    return
                self.results[rc_id] = RunnerResult(participant=p)
            target = self.results[rc_id]
            self._record_lap_locked(target, elapsed_ms, now, source="결승선")
        self._publish_ranks()

    def _in_pass_cooldown(self, rc_id: str, now: float) -> bool:
        until = self._pass_cooldown_until.get(rc_id, 0.0)
        return now < until

    def _record_lap_locked(
        self,
        target: RunnerResult,
        elapsed_ms: float,
        now: float,
        source: str,
    ) -> None:
        """호출 전 self._lock 획득 필요."""
        rc_id = target.participant.rc_id
        if self._in_pass_cooldown(rc_id, now):
            remain = self._pass_cooldown_until[rc_id] - now
            self._emit_status(
                f"{target.participant.name} 재기록 대기 ({remain:.1f}초 남음)"
            )
            return
        if len(target.lap_times_ms) >= self.config.lap_count:
            return

        prev = sum(target.lap_times_ms)
        lap_ms = max(0.0, elapsed_ms - prev)
        target.lap_times_ms.append(lap_ms)
        if len(target.lap_times_ms) >= self.config.lap_count:
            target.finished = True
        # 통과 후 해당 RC-ID 7초간 기록 중단
        self._pass_cooldown_until[rc_id] = now + self.config.pass_cooldown_s
        self._emit_status(
            f"{target.participant.name} {source} 랩{len(target.lap_times_ms)} "
            f"{target.format_lap(len(target.lap_times_ms) - 1)} "
            f"(이후 {self.config.pass_cooldown_s:.0f}초 재기록 금지)"
        )
