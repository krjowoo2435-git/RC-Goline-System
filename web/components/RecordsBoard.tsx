"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { RaceRecord } from "@/lib/records";

type Props = {
  initialRecords: RaceRecord[];
};

export default function RecordsBoard({ initialRecords }: Props) {
  const [records, setRecords] = useState<RaceRecord[]>(initialRecords);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch("/api/records", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { records: RaceRecord[] };
        if (!cancelled && Array.isArray(data.records)) {
          setRecords(data.records);
        }
      } catch {
        // ignore polling errors
      }
    };
    const id = window.setInterval(tick, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const ordered = useMemo(() => {
    const active = records
      .filter((r) => !r.disqualified)
      .sort((a, b) => (a.rank || 0) - (b.rank || 0));
    const erased = records.filter((r) => r.disqualified);
    return [...active, ...erased];
  }, [records]);

  function goToStudent(raw: string) {
    const q = raw.trim();
    if (!q) {
      setActiveId(null);
      setStatus(null);
      return;
    }
    const match = ordered.find(
      (r) => r.student_id === q || r.student_id.includes(q),
    );
    if (!match) {
      setActiveId(null);
      setStatus(`학번 "${q}" 기록을 찾지 못했습니다.`);
      return;
    }
    setActiveId(match.student_id);
    setStatus(
      match.disqualified
        ? `${match.student_id} · ${match.name} · 기록말소`
        : `${match.rank}등 · ${match.student_id} · ${match.name}`,
    );
    const el = rowRefs.current.get(match.student_id);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    goToStudent(query);
  }

  return (
    <div className="phone-shell">
      <form className="search-bar" onSubmit={onSubmit} role="search">
        <button type="submit" className="search-icon" aria-label="학번 검색">
          <img src="/search-icon.svg" alt="" width={48} height={48} />
        </button>
        <input
          className="search-input"
          type="search"
          inputMode="numeric"
          placeholder="검색창"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!e.target.value.trim()) {
              setActiveId(null);
              setStatus(null);
            }
          }}
          aria-label="학번 검색"
        />
      </form>

      <section className="records-panel" aria-label="기록 표시">
        {status ? <p className="search-status">{status}</p> : null}

        <div className="records-scroll">
          {ordered.length === 0 ? (
            <p className="empty">기록표시</p>
          ) : (
            <table className="records-table">
              <thead>
                <tr>
                  <th>등수</th>
                  <th>학번</th>
                  <th>MM:SS:MS</th>
                </tr>
              </thead>
              <tbody>
                {ordered.map((row) => {
                  const key = `${row.student_id}-${row.name}-${row.disqualified ? "dq" : row.rank}`;
                  const active = activeId === row.student_id;
                  const className = [
                    active ? "is-active" : "",
                    row.disqualified ? "is-erased" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  return (
                    <tr
                      key={key}
                      ref={(node) => {
                        if (node && row.student_id) {
                          rowRefs.current.set(row.student_id, node);
                        }
                      }}
                      data-student-id={row.student_id}
                      className={className || undefined}
                    >
                      <td>{row.disqualified ? "말소" : row.rank || "-"}</td>
                      <td>{row.student_id}</td>
                      <td>{row.disqualified ? "말소" : row.total || "--:--:---"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
