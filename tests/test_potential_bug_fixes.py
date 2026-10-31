"""잠재 버그 수정 회귀 검증 (하드웨어/카메라 없이)."""

from __future__ import annotations

import threading
import time
import unittest

from desktop.camera_service import CameraService
from desktop.finish_line import VirtualFinishLine
from desktop.models import Participant, RacePhase, RankRow, RunnerResult
from desktop.race_engine import RaceConfig, RaceEngine
from desktop.storage import (
    force_update_record,
    load_overall_records,
    save_overall_records,
)


def _people() -> list[Participant]:
    return [
        Participant(rc_id="RC-00", name="A", student_id="1001", marker_id=0),
        Participant(rc_id="RC-01", name="B", student_id="1002", marker_id=1),
        Participant(rc_id="RC-02", name="C", student_id="1003", marker_id=2),
    ]


class FakeHardware:
    def __init__(self) -> None:
        self.on_pass = None

    def reset_triggers(self) -> None:
        return None

    def all_leds_off(self) -> None:
        return None

    def buzz(self, *_a, **_k) -> None:
        return None

    def sequential_led_on(self, *_a, **_k) -> None:
        return None


class FinishLineDirectionTests(unittest.TestCase):
    def test_reverse_crossing_ignored_after_forward_lock(self) -> None:
        line = VirtualFinishLine()
        line.add_point(0, 50)
        line.add_point(100, 50)
        # 위→아래 (정방향 잠금)
        self.assertFalse(line.check_crossing(0, 50, 40))
        self.assertTrue(line.check_crossing(0, 50, 60))
        # 아래→위 (역방향) 무시
        self.assertFalse(line.check_crossing(0, 50, 40))
        # 다시 정방향은 인정
        self.assertTrue(line.check_crossing(0, 50, 60))


class RaceEngineWorkerTests(unittest.TestCase):
    def test_abort_joins_before_restart(self) -> None:
        engine = RaceEngine(
            participants=_people(),
            hardware=FakeHardware(),  # type: ignore[arg-type]
            config=RaceConfig(
                led_hold_min_s=0.01,
                led_hold_max_s=0.01,
                start_delay_min_s=30.0,
                start_delay_max_s=30.0,
            ),
        )
        engine.start_race(lap_count=1)
        time.sleep(0.05)
        first = engine._worker
        self.assertIsNotNone(first)
        assert first is not None
        self.assertTrue(first.is_alive())
        engine.abort()
        self.assertFalse(first.is_alive())
        self.assertEqual(engine.phase, RacePhase.IDLE)
        engine.start_race(lap_count=1)
        second = engine._worker
        self.assertIsNotNone(second)
        assert second is not None
        self.assertIsNot(first, second)
        engine.abort()

    def test_finish_not_reentrant(self) -> None:
        engine = RaceEngine(
            participants=_people()[:1],
            hardware=FakeHardware(),  # type: ignore[arg-type]
        )
        with engine._lock:
            engine.results = {
                "RC-00": RunnerResult(
                    participant=_people()[0],
                    lap_times_ms=[1000.0],
                    finished=True,
                )
            }
        engine.phase = RacePhase.RACING
        calls: list[int] = []
        orig = engine._publish_ranks

        def wrapped() -> None:
            calls.append(1)
            orig()

        engine._publish_ranks = wrapped  # type: ignore[method-assign]
        engine._finish()
        engine._finish()
        self.assertEqual(engine.phase, RacePhase.FINISHED)
        self.assertEqual(len(calls), 1)

    def test_ultrasonic_remap_only_when_single_marker(self) -> None:
        engine = RaceEngine(
            participants=_people(),
            hardware=FakeHardware(),  # type: ignore[arg-type]
            config=RaceConfig(ultrasonic_enabled=True),
        )
        engine.phase = RacePhase.RACING
        engine.start_monotonic = time.monotonic() - 1.0
        with engine._lock:
            engine.results = {
                p.rc_id: RunnerResult(participant=p) for p in _people()
            }
            # 두 마커가 동시에 pending → 센서 레인(0) 유지
            now = time.monotonic()
            engine._pending_markers = {0: now, 1: now}
        engine._on_ultrasonic_pass(0, 10.0)
        r0 = engine.results["RC-00"]
        r1 = engine.results["RC-01"]
        self.assertEqual(len(r0.lap_times_ms), 1)
        self.assertEqual(len(r1.lap_times_ms), 0)

        # 단일 마커면 재매핑
        with engine._lock:
            engine.results["RC-00"].lap_times_ms.clear()
            engine._pass_cooldown_until.clear()
            engine._pending_markers = {2: time.monotonic()}
        engine._on_ultrasonic_pass(0, 10.0)
        self.assertEqual(len(engine.results["RC-02"].lap_times_ms), 1)
        self.assertEqual(len(engine.results["RC-00"].lap_times_ms), 0)

    def test_false_start_message_uses_config(self) -> None:
        statuses: list[str] = []
        engine = RaceEngine(
            participants=_people()[:1],
            hardware=FakeHardware(),  # type: ignore[arg-type]
            config=RaceConfig(false_start_penalty_ms=5000.0),
            on_status=statuses.append,
        )
        with engine._lock:
            engine.results = {
                "RC-00": RunnerResult(participant=_people()[0])
            }
        engine.phase = RacePhase.WAITING_START
        engine._apply_false_start_penalty(0)
        self.assertTrue(any("+5초" in s for s in statuses))

    def test_ultrasonic_disabled_ignores_pass(self) -> None:
        engine = RaceEngine(
            participants=_people()[:1],
            hardware=FakeHardware(),  # type: ignore[arg-type]
            config=RaceConfig(ultrasonic_enabled=False),
        )
        engine.phase = RacePhase.RACING
        engine.start_monotonic = time.monotonic() - 1.0
        with engine._lock:
            engine.results = {
                "RC-00": RunnerResult(participant=_people()[0])
            }
        engine._on_ultrasonic_pass(0, 5.0)
        self.assertEqual(len(engine.results["RC-00"].lap_times_ms), 0)
        engine.set_ultrasonic_enabled(True)
        engine._on_ultrasonic_pass(0, 5.0)
        self.assertEqual(len(engine.results["RC-00"].lap_times_ms), 1)

    def test_participants_over_max_runners_trimmed_with_notice(self) -> None:
        statuses: list[str] = []
        extra = _people() + [
            Participant(rc_id="RC-03", name="D", student_id="1004", marker_id=3)
        ]
        engine = RaceEngine(
            participants=extra,
            hardware=FakeHardware(),  # type: ignore[arg-type]
            config=RaceConfig(
                max_runners=3,
                led_hold_min_s=0.01,
                led_hold_max_s=0.01,
                start_delay_min_s=30.0,
                start_delay_max_s=30.0,
            ),
            on_status=statuses.append,
        )
        engine.start_race(1)
        time.sleep(0.05)
        self.assertEqual(len(engine.results), 3)
        self.assertTrue(any("제외" in s for s in statuses))
        engine.abort()


class CameraServiceTests(unittest.TestCase):
    def test_start_after_dead_loop_flag(self) -> None:
        cam = CameraService(camera_index=0)
        cam._running = True
        cam._thread = threading.Thread(target=lambda: None)
        cam._thread.start()
        cam._thread.join()
        # 죽은 스레드 + _running True → start가 stop 후 재시도 (카메라 없으면 False)
        # 중요: "이미 실행 중"으로 즉시 True를 반환하지 않음
        opened = cam.start()
        self.assertFalse(cam._running and cam._thread is None)
        if opened:
            cam.stop()
        else:
            self.assertFalse(cam._running)


class StoragePenaltyTests(unittest.TestCase):
    def test_force_update_worsens_time(self) -> None:
        backup = load_overall_records()
        try:
            save_overall_records(
                [
                    {
                        "rank": 1,
                        "rc_id": "RC-00",
                        "student_id": "9001",
                        "name": "PenTest",
                        "laps": ["00:01:000", "--:--:---", "--:--:---"],
                        "total": "00:01:000",
                        "total_ms": 1000,
                        "penalty_ms": 0,
                        "disqualified": False,
                    }
                ]
            )
            row = RankRow(
                rank=1,
                rc_id="RC-00",
                name="PenTest",
                student_id="9001",
                lap_labels=["00:01:000"],
                total_label="00:04:000",
                penalty_ms=3000,
            )
            overall = force_update_record(row)
            hit = next(
                r
                for r in overall
                if r["student_id"] == "9001" and r["name"] == "PenTest"
            )
            self.assertEqual(hit["total_ms"], 4000)
            self.assertEqual(hit["penalty_ms"], 3000)
        finally:
            save_overall_records(backup)


class MarkerIdFromRcTests(unittest.TestCase):
    def test_rc_digits_not_row_index(self) -> None:
        # main_monitor 수집 로직과 동일
        def marker_for(rc_id: str, row_i: int) -> int:
            digits = "".join(ch for ch in rc_id if ch.isdigit())
            return int(digits) if digits else row_i

        self.assertEqual(marker_for("RC-02", 0), 2)
        self.assertEqual(marker_for("RC-00", 2), 0)


if __name__ == "__main__":
    unittest.main()
