from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import Participant, RankRow

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

PARTICIPANTS_JSON = DATA_DIR / "participants.json"
PARTICIPANTS_CSV = DATA_DIR / "participants.csv"
RECORDS_JSON = DATA_DIR / "records.json"
RECORDS_CSV = DATA_DIR / "records.csv"
# 하위 호환
HISTORY_PATH = DATA_DIR / "history.json"

PARTICIPANT_CSV_FIELDS = ["student_id", "name", "rc_id", "marker_id"]
RECORD_CSV_FIELDS = [
    "rank",
    "rc_id",
    "student_id",
    "name",
    "lap1",
    "lap2",
    "lap3",
    "total",
    "total_ms",
    "penalty_ms",
]


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ----- 참가자 (JSON + CSV 병렬) -----


def load_participants(path: Path | None = None) -> list[Participant]:
    target = path or PARTICIPANTS_JSON
    if not target.exists():
        # CSV만 있는 경우 복구
        if PARTICIPANTS_CSV.exists():
            return _load_participants_csv(PARTICIPANTS_CSV)
        return []
    with target.open(encoding="utf-8") as f:
        raw = json.load(f)
    items = raw.get("participants", []) if isinstance(raw, dict) else raw
    return [Participant.from_dict(item) for item in items]


def _load_participants_csv(path: Path) -> list[Participant]:
    people: list[Participant] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            people.append(Participant.from_dict(row))
    return people


def save_participants(
    participants: list[Participant],
    json_path: Path | None = None,
    csv_path: Path | None = None,
) -> None:
    """참가자를 JSON·CSV에 동시에 저장 (웹 연동용 병렬 포맷)."""
    _ensure_data_dir()
    jpath = json_path or PARTICIPANTS_JSON
    cpath = csv_path or PARTICIPANTS_CSV

    payload = {
        "participants": [
            {
                "student_id": p.student_id,
                "name": p.name,
                "rc_id": p.rc_id,
                "marker_id": p.marker_id,
            }
            for p in participants
        ]
    }
    with jpath.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with cpath.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PARTICIPANT_CSV_FIELDS)
        writer.writeheader()
        for p in participants:
            writer.writerow(
                {
                    "student_id": p.student_id,
                    "name": p.name,
                    "rc_id": p.rc_id,
                    "marker_id": p.marker_id,
                }
            )


# ----- 전체 기록 / 역대 기록 (JSON + CSV 병렬) -----


def load_overall_records(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or RECORDS_JSON
    if not target.exists():
        # 구 history.json 마이그레이션 시도
        if HISTORY_PATH.exists():
            return _migrate_history_to_overall()
        if RECORDS_CSV.exists():
            return _load_records_csv(RECORDS_CSV)
        return []
    with target.open(encoding="utf-8") as f:
        raw = json.load(f)
    return list(raw.get("records", []))


def _load_records_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            laps = [row.get("lap1", ""), row.get("lap2", ""), row.get("lap3", "")]
            rows.append(
                {
                    "rank": int(row.get("rank") or 0),
                    "rc_id": row.get("rc_id", ""),
                    "student_id": row.get("student_id", ""),
                    "name": row.get("name", ""),
                    "laps": laps,
                    "total": row.get("total", ""),
                    "total_ms": int(float(row.get("total_ms") or 0)),
                    "penalty_ms": float(row.get("penalty_ms") or 0),
                }
            )
    return rows


def _migrate_history_to_overall() -> list[dict[str, Any]]:
    legacy = load_history()
    flat: list[dict[str, Any]] = []
    for session in legacy:
        for entry in session.get("entries", []):
            flat.append(
                {
                    "rank": int(entry.get("rank") or 0),
                    "rc_id": entry.get("rc_id", ""),
                    "student_id": entry.get("student_id", ""),
                    "name": entry.get("name", ""),
                    "laps": list(entry.get("laps") or []),
                    "total": entry.get("total", ""),
                    "total_ms": _parse_total_ms(entry.get("total", "")),
                    "penalty_ms": float(entry.get("penalty_ms") or 0),
                }
            )
    flat = _sort_overall(flat)
    save_overall_records(flat)
    return flat


def _parse_total_ms(label: str) -> int:
    # MM:SS:MS
    try:
        parts = label.split(":")
        if len(parts) != 3:
            return 0
        minutes, seconds, millis = (int(parts[0]), int(parts[1]), int(parts[2]))
        return minutes * 60_000 + seconds * 1000 + millis
    except ValueError:
        return 0


def _sort_overall(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """total 기준 오름차순(빠른 순) → rank 1,2,3…"""
    ordered = sorted(records, key=lambda r: int(r.get("total_ms") or 10**12))
    for i, row in enumerate(ordered, start=1):
        row["rank"] = i
    return ordered


def save_overall_records(
    records: list[dict[str, Any]],
    json_path: Path | None = None,
    csv_path: Path | None = None,
) -> None:
    """전체 기록을 JSON·CSV에 동시에 저장."""
    _ensure_data_dir()
    ordered = _sort_overall(list(records))
    jpath = json_path or RECORDS_JSON
    cpath = csv_path or RECORDS_CSV

    with jpath.open("w", encoding="utf-8") as f:
        json.dump({"records": ordered}, f, ensure_ascii=False, indent=2)

    with cpath.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RECORD_CSV_FIELDS)
        writer.writeheader()
        for row in ordered:
            laps = list(row.get("laps") or [])
            while len(laps) < 3:
                laps.append("--:--:---")
            writer.writerow(
                {
                    "rank": row.get("rank", 0),
                    "rc_id": row.get("rc_id", ""),
                    "student_id": row.get("student_id", ""),
                    "name": row.get("name", ""),
                    "lap1": laps[0],
                    "lap2": laps[1],
                    "lap3": laps[2],
                    "total": row.get("total", ""),
                    "total_ms": row.get("total_ms", 0),
                    "penalty_ms": row.get("penalty_ms", 0),
                }
            )


def append_race_results(rows: list[RankRow]) -> list[dict[str, Any]]:
    """
    게임 종료 시 전체 기록에 추가하고 JSON+CSV로 병렬 저장.
    흐름: 이름·학번·토탈을 전체 기록에 넣고 total 기준 재정렬.
    """
    overall = load_overall_records()
    for row in rows:
        if row.rank <= 0:
            continue
        total_ms = _parse_total_ms(row.total_label)
        overall.append(
            {
                "rank": 0,
                "rc_id": row.rc_id,
                "student_id": row.student_id,
                "name": row.name,
                "laps": list(row.lap_labels),
                "total": row.total_label,
                "total_ms": total_ms,
                "penalty_ms": row.penalty_ms,
            }
        )
    overall = _sort_overall(overall)
    save_overall_records(overall)
    # 세션 히스토리도 유지(디버그/호환)
    append_history(rows)
    return overall


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or HISTORY_PATH
    if not target.exists():
        return []
    with target.open(encoding="utf-8") as f:
        raw = json.load(f)
    return list(raw.get("records", []))


def append_history(rows: list[RankRow], path: Path | None = None) -> None:
    target = path or HISTORY_PATH
    _ensure_data_dir()
    records = load_history(target)
    records.append(
        {
            "entries": [
                {
                    "rank": row.rank,
                    "rc_id": row.rc_id,
                    "name": row.name,
                    "student_id": row.student_id,
                    "laps": row.lap_labels,
                    "total": row.total_label,
                    "penalty_ms": row.penalty_ms,
                }
                for row in rows
            ]
        }
    )
    with target.open("w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)


def participant_by_marker(
    participants: list[Participant], marker_id: int
) -> Participant | None:
    for p in participants:
        if p.marker_id == marker_id:
            return p
    return None
