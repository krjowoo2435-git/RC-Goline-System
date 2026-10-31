from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import Participant, RankRow

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UPLOAD_SECRET_FILE = DATA_DIR / "upload_secret.txt"

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
    "disqualified",
]


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json_object(path: Path) -> dict[str, Any] | list[Any] | None:
    """빈 파일·깨진 JSON은 None (예외 대신)."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    return raw


# ----- 참가자 (JSON + CSV 병렬) -----


def load_participants(path: Path | None = None) -> list[Participant]:
    target = path or PARTICIPANTS_JSON
    raw = _read_json_object(target)
    if raw is None:
        if PARTICIPANTS_CSV.exists():
            return _load_participants_csv(PARTICIPANTS_CSV)
        return []
    items = raw.get("participants", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
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
    raw = _read_json_object(target)
    if isinstance(raw, dict):
        return _sort_overall(list(raw.get("records") or []))
    if isinstance(raw, list):
        return _sort_overall(list(raw))

    # JSON 없음/빈파일/깨짐 → CSV 또는 history 폴백
    if RECORDS_CSV.exists() and RECORDS_CSV.stat().st_size > 0:
        rows = _load_records_csv(RECORDS_CSV)
        if rows:
            return _sort_overall(rows)
    hist = _read_json_object(HISTORY_PATH)
    if hist is not None:
        return _migrate_history_to_overall()
    return []


def _load_records_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            laps = [row.get("lap1", ""), row.get("lap2", ""), row.get("lap3", "")]
            dq_raw = str(row.get("disqualified", "")).strip().lower()
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
                    "disqualified": dq_raw in ("1", "true", "yes", "dq", "말소"),
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


def _record_identity_key(student_id: str, name: str) -> str:
    """기록 식별: 학번 + 이름 (공백 무시, 대소문자 무시)."""
    sid = str(student_id or "").strip().casefold()
    nm = str(name or "").strip().casefold()
    return f"{sid}\0{nm}"


def _normalize_record_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    row = dict(raw)
    sid = str(row.get("student_id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not sid or not name:
        return None
    dq = bool(row.get("disqualified"))
    if dq:
        total_ms = 10**12 - 1
        total = "말소"
        laps = ["말소", "말소", "말소"]
    else:
        total_ms = int(row.get("total_ms") or _parse_total_ms(str(row.get("total") or "")))
        total = str(row.get("total") or "--:--:---")
        laps = list(row.get("laps") or [])
        while len(laps) < 3:
            laps.append("--:--:---")
        laps = laps[:3]
    row.update(
        {
            "student_id": sid,
            "name": name,
            "rc_id": str(row.get("rc_id") or ""),
            "total_ms": total_ms,
            "total": total,
            "laps": laps,
            "penalty_ms": float(row.get("penalty_ms") or 0),
            "disqualified": dq,
        }
    )
    return row


def _merge_best_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """학번+이름 기준. 말소는 즉시 반영, 정상 기록은 더 빠를 때만 갱신."""
    best: dict[str, dict[str, Any]] = {}
    for raw in records:
        row = _normalize_record_row(raw if isinstance(raw, dict) else {})
        if row is None:
            continue
        key = _record_identity_key(row["student_id"], row["name"])
        prev = best.get(key)
        if row["disqualified"]:
            # 기록 말소 — 기존 성적 덮어씀
            best[key] = row
            continue
        if prev is None:
            best[key] = row
            continue
        if prev.get("disqualified"):
            # 말소 후 재경기 정상 기록 → 복구
            best[key] = row
            continue
        if int(row["total_ms"]) < int(prev.get("total_ms") or 10**12):
            best[key] = row
    return list(best.values())


def _sort_overall(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """정상 기록 빠른 순 순위 → 말소는 맨 뒤(rank=0)."""
    merged = _merge_best_records(records)
    active = [r for r in merged if not r.get("disqualified")]
    erased = [r for r in merged if r.get("disqualified")]
    ordered = sorted(active, key=lambda r: int(r.get("total_ms") or 10**12))
    for i, row in enumerate(ordered, start=1):
        row["rank"] = i
    for row in erased:
        row["rank"] = 0
    return ordered + erased


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
                    "disqualified": "1" if row.get("disqualified") else "0",
                }
            )


def append_race_results(
    rows: list[RankRow],
) -> tuple[list[dict[str, Any]], int, int]:
    """
    게임 종료 시 전체 기록에 반영하고 JSON+CSV로 병렬 저장.
    식별: 학번+이름. 기존보다 성적이 나쁘거나 같으면 갱신하지 않음.

    Returns:
        (전체기록, 갱신/신규 수, 미갱신(성적 저하·동일) 수)
    """
    overall = load_overall_records()
    existing = {
        _record_identity_key(str(r.get("student_id", "")), str(r.get("name", ""))): r
        for r in overall
    }
    accepted = 0
    skipped = 0
    for row in rows:
        sid = str(row.student_id or "").strip()
        name = str(row.name or "").strip()
        if not sid or not name:
            continue
        if row.disqualified:
            overall.append(
                {
                    "rank": 0,
                    "rc_id": row.rc_id,
                    "student_id": sid,
                    "name": name,
                    "laps": ["말소", "말소", "말소"],
                    "total": "말소",
                    "total_ms": 10**12 - 1,
                    "penalty_ms": 0,
                    "disqualified": True,
                }
            )
            accepted += 1
            continue
        if row.rank <= 0:
            continue
        total_ms = _parse_total_ms(row.total_label)
        if total_ms <= 0 and not row.total_label:
            continue
        key = _record_identity_key(sid, name)
        prev = existing.get(key)
        if (
            prev is not None
            and not prev.get("disqualified")
            and total_ms >= int(prev.get("total_ms") or 10**12)
        ):
            skipped += 1
            continue
        overall.append(
            {
                "rank": 0,
                "rc_id": row.rc_id,
                "student_id": sid,
                "name": name,
                "laps": list(row.lap_labels),
                "total": row.total_label,
                "total_ms": total_ms,
                "penalty_ms": row.penalty_ms,
                "disqualified": False,
            }
        )
        accepted += 1
    # 세션 히스토리는 회차별 원본 유지
    append_history(rows)
    overall = _sort_overall(overall)
    if accepted > 0:
        save_overall_records(overall)
    return overall, accepted, skipped


def clear_all_records() -> None:
    """전체 기록·히스토리를 빈 상태로 초기화 (JSON/CSV)."""
    _ensure_data_dir()
    save_overall_records([])
    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        json.dump({"records": []}, f, ensure_ascii=False, indent=2)


def _normalize_secret(raw: str) -> str:
    """공백·감싸는 따옴표 제거 (복붙 시 \"값\" 형태 대비)."""
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def load_upload_secret() -> str:
    """웹 업로드 시크릿. 환경변수 → data/upload_secret.txt → 루트 .env 순."""
    import os

    env = _normalize_secret(os.environ.get("RCGLS_UPLOAD_SECRET", ""))
    if env:
        return env

    if UPLOAD_SECRET_FILE.exists():
        try:
            text = UPLOAD_SECRET_FILE.read_text(encoding="utf-8").strip()
            # 첫 줄만 (주석 # 무시)
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.upper().startswith("RCGLS_UPLOAD_SECRET="):
                    return _normalize_secret(line.split("=", 1)[1])
                return _normalize_secret(line)
        except OSError:
            pass

    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip() == "RCGLS_UPLOAD_SECRET":
                    return _normalize_secret(val)
        except OSError:
            pass
    return ""


def mark_record_erased(
    student_id: str,
    name: str,
    rc_id: str = "",
) -> list[dict[str, Any]]:
    """수동 기록말소 — 학번+이름 기록을 말소 상태로 즉시 저장."""
    sid = str(student_id or "").strip()
    nm = str(name or "").strip()
    if not sid or not nm:
        return load_overall_records()
    overall = load_overall_records()
    overall.append(
        {
            "rank": 0,
            "rc_id": rc_id,
            "student_id": sid,
            "name": nm,
            "laps": ["말소", "말소", "말소"],
            "total": "말소",
            "total_ms": 10**12 - 1,
            "penalty_ms": 0,
            "disqualified": True,
        }
    )
    overall = _sort_overall(overall)
    save_overall_records(overall)
    return overall


def force_update_record(row: RankRow) -> list[dict[str, Any]]:
    """경기 종료 후 패널티 등 — 학번+이름 기록을 강제 갱신(성적 저하 포함)."""
    sid = str(row.student_id or "").strip()
    name = str(row.name or "").strip()
    if not sid or not name:
        return load_overall_records()
    if row.disqualified:
        return mark_record_erased(sid, name, rc_id=row.rc_id)

    total_ms = _parse_total_ms(row.total_label)
    overall = load_overall_records()
    key = _record_identity_key(sid, name)
    replaced = False
    for i, existing in enumerate(overall):
        if _record_identity_key(
            str(existing.get("student_id", "")), str(existing.get("name", ""))
        ) != key:
            continue
        overall[i] = {
            "rank": 0,
            "rc_id": row.rc_id,
            "student_id": sid,
            "name": name,
            "laps": list(row.lap_labels),
            "total": row.total_label,
            "total_ms": total_ms,
            "penalty_ms": row.penalty_ms,
            "disqualified": False,
        }
        replaced = True
        break
    if not replaced:
        overall.append(
            {
                "rank": 0,
                "rc_id": row.rc_id,
                "student_id": sid,
                "name": name,
                "laps": list(row.lap_labels),
                "total": row.total_label,
                "total_ms": total_ms,
                "penalty_ms": row.penalty_ms,
                "disqualified": False,
            }
        )
    overall = _sort_overall(overall)
    save_overall_records(overall)
    return overall


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or HISTORY_PATH
    raw = _read_json_object(target)
    if isinstance(raw, dict):
        return list(raw.get("records") or [])
    if isinstance(raw, list):
        return list(raw)
    return []


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
                if row.rank > 0 and not row.disqualified
            ]
        }
    )
    # 빈 entries만 있는 회차는 생략
    if not records[-1]["entries"]:
        records.pop()
        return
    with target.open("w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)


def participant_by_marker(
    participants: list[Participant], marker_id: int
) -> Participant | None:
    for p in participants:
        if p.marker_id == marker_id:
            return p
    return None
