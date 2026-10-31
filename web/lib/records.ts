import { createClient as createBrowserClient } from "@supabase/supabase-js";
import { promises as fs } from "fs";
import path from "path";

export type RaceRecord = {
  rank: number;
  rc_id: string;
  student_id: string;
  name: string;
  laps: string[];
  total: string;
  total_ms: number;
  penalty_ms: number;
  disqualified: boolean;
};

const EMPTY_LAP = "--:--:---";
const ERASED_MS = 1_000_000_000_000 - 1;

type DbRow = {
  student_id: string;
  rc_id: string;
  name: string;
  rank: number;
  lap1: string;
  lap2: string;
  lap3: string;
  total: string;
  total_ms: number;
  penalty_ms: number;
  disqualified?: boolean | null;
};

function projectDataPath(): string {
  return path.join(process.cwd(), "..", "data", "records.json");
}

function localFallbackPath(): string {
  return path.join(process.cwd(), "data", "records.json");
}

function supabaseUrl(): string | undefined {
  return process.env.NEXT_PUBLIC_SUPABASE_URL;
}

function supabaseKey(): string | undefined {
  return (
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

export function isSupabaseConfigured(): boolean {
  const url = supabaseUrl();
  const key = supabaseKey();
  return Boolean(url && key && !url.includes("YOUR_PROJECT_REF"));
}

function adminClient() {
  const url = supabaseUrl();
  const key = supabaseKey();
  if (!url || !key) {
    throw new Error("Supabase 환경변수가 없습니다.");
  }
  return createBrowserClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

function asBool(v: unknown): boolean {
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v !== 0;
  const s = String(v ?? "").trim().toLowerCase();
  return ["1", "true", "yes", "dq", "말소"].includes(s);
}

export function normalizeRecord(
  raw: Partial<RaceRecord> & Record<string, unknown>,
): RaceRecord {
  const dq = asBool(raw.disqualified) || String(raw.total ?? "") === "말소";
  const lapsRaw = Array.isArray(raw.laps)
    ? raw.laps.map(String)
    : [raw.lap1, raw.lap2, raw.lap3].map((v) =>
        v == null || v === "" ? EMPTY_LAP : String(v),
      );
  let laps = [...lapsRaw];
  while (laps.length < 3) laps.push(EMPTY_LAP);
  laps = laps.slice(0, 3);

  if (dq) {
    return {
      rank: 0,
      rc_id: String(raw.rc_id ?? ""),
      student_id: String(raw.student_id ?? ""),
      name: String(raw.name ?? ""),
      laps: ["말소", "말소", "말소"],
      total: "말소",
      total_ms: ERASED_MS,
      penalty_ms: 0,
      disqualified: true,
    };
  }

  return {
    rank: Number(raw.rank) || 0,
    rc_id: String(raw.rc_id ?? ""),
    student_id: String(raw.student_id ?? ""),
    name: String(raw.name ?? ""),
    laps,
    total: String(raw.total ?? EMPTY_LAP),
    total_ms: Number(raw.total_ms) || 0,
    penalty_ms: Number(raw.penalty_ms) || 0,
    disqualified: false,
  };
}

function toDbRow(record: RaceRecord): DbRow {
  const laps = [...record.laps];
  while (laps.length < 3) laps.push(EMPTY_LAP);
  return {
    student_id: record.student_id,
    rc_id: record.rc_id,
    name: record.name,
    rank: record.rank,
    lap1: laps[0],
    lap2: laps[1],
    lap3: laps[2],
    total: record.total,
    total_ms: record.total_ms,
    penalty_ms: record.penalty_ms,
    disqualified: record.disqualified,
  };
}

function fromDbRow(row: DbRow): RaceRecord {
  return normalizeRecord({
    student_id: row.student_id,
    rc_id: row.rc_id,
    name: row.name,
    rank: row.rank,
    laps: [row.lap1, row.lap2, row.lap3],
    total: row.total,
    total_ms: row.total_ms,
    penalty_ms: row.penalty_ms,
    disqualified: row.disqualified ?? false,
  });
}

function identityKey(studentId: string, name: string): string {
  return `${studentId.trim().toLowerCase()}\0${name.trim().toLowerCase()}`;
}

function sortRecords(records: RaceRecord[]): RaceRecord[] {
  const best = new Map<string, RaceRecord>();
  for (const raw of records.map(normalizeRecord)) {
    if (!raw.student_id || !raw.name) continue;
    const key = identityKey(raw.student_id, raw.name);
    const prev = best.get(key);
    if (raw.disqualified) {
      best.set(key, raw);
      continue;
    }
    if (!prev) {
      best.set(key, raw);
      continue;
    }
    if (prev.disqualified) {
      best.set(key, raw);
      continue;
    }
    if ((raw.total_ms || 1e12) < (prev.total_ms || 1e12)) {
      best.set(key, raw);
    }
  }

  const all = [...best.values()];
  const active = all
    .filter((r) => !r.disqualified)
    .sort((a, b) => (a.total_ms || 1e12) - (b.total_ms || 1e12))
    .map((row, i) => ({ ...row, rank: i + 1 }));
  const erased = all
    .filter((r) => r.disqualified)
    .map((row) => ({ ...row, rank: 0 }));
  return [...active, ...erased];
}

async function readRecordsFile(): Promise<RaceRecord[]> {
  const candidates = [projectDataPath(), localFallbackPath()];
  for (const file of candidates) {
    try {
      const text = await fs.readFile(file, "utf-8");
      const raw = JSON.parse(text) as { records?: unknown[] };
      const list = Array.isArray(raw.records) ? raw.records : [];
      return sortRecords(
        list.map((item) =>
          normalizeRecord(item as Partial<RaceRecord> & Record<string, unknown>),
        ),
      );
    } catch {
      // try next
    }
  }
  return [];
}

async function writeRecordsFile(records: RaceRecord[]): Promise<string> {
  const ordered = sortRecords(records);
  const payload = JSON.stringify({ records: ordered }, null, 2);
  const primary = projectDataPath();
  const fallback = localFallbackPath();

  try {
    await fs.mkdir(path.dirname(primary), { recursive: true });
    await fs.writeFile(primary, payload, "utf-8");
    return primary;
  } catch {
    await fs.mkdir(path.dirname(fallback), { recursive: true });
    await fs.writeFile(fallback, payload, "utf-8");
    return fallback;
  }
}

const SELECT_COLS =
  "student_id,rc_id,name,rank,lap1,lap2,lap3,total,total_ms,penalty_ms,disqualified";

export async function readRecordsFromSupabase(): Promise<RaceRecord[]> {
  const supabase = adminClient();
  const primary = await supabase
    .from("race_records")
    .select(SELECT_COLS)
    .order("rank", { ascending: true });

  let rows: DbRow[] | null = (primary.data as DbRow[] | null) ?? null;
  let error = primary.error;

  // disqualified 컬럼 마이그레이션 전이면 구 컬럼만 조회
  if (error && /disqualified/i.test(error.message || "")) {
    const fallback = await supabase
      .from("race_records")
      .select(
        "student_id,rc_id,name,rank,lap1,lap2,lap3,total,total_ms,penalty_ms",
      )
      .order("rank", { ascending: true });
    rows = (fallback.data as DbRow[] | null) ?? null;
    error = fallback.error;
  }

  if (error) throw error;
  return sortRecords(rows?.map(fromDbRow) ?? []);
}

export async function replaceRecordsInSupabase(
  records: RaceRecord[],
): Promise<RaceRecord[]> {
  // 기존 기록과 병합(학번+이름 최고기록 유지) 후 upsert — 전체 삭제 덮어쓰기 방지
  const existing = await readRecordsFromSupabase();
  const ordered = sortRecords([...existing, ...records]);
  const supabase = adminClient();

  if (ordered.length === 0) return existing;

  const { data, error } = await supabase
    .from("race_records")
    .upsert(ordered.map(toDbRow), { onConflict: "student_id,name" })
    .select(SELECT_COLS);

  if (error) throw error;
  return sortRecords((data as DbRow[] | null)?.map(fromDbRow) ?? ordered);
}

/** 전체 기록 삭제 (초기화). 병합 업로드와 별도. */
export async function clearAllRecordsStore(): Promise<{
  records: RaceRecord[];
  source: "supabase" | "file";
  path?: string;
}> {
  if (isSupabaseConfigured()) {
    try {
      const supabase = adminClient();
      const { error } = await supabase
        .from("race_records")
        .delete()
        .neq("student_id", "");
      if (error) throw error;
      try {
        await writeRecordsFile([]);
      } catch {
        // ignore backup failure
      }
      return { records: [], source: "supabase" };
    } catch (err) {
      const filePath = await writeRecordsFile([]);
      return {
        records: [],
        source: "file",
        path: `${filePath} (supabase 오류: ${String(err)})`,
      };
    }
  }

  const filePath = await writeRecordsFile([]);
  return { records: [], source: "file", path: filePath };
}

export async function readRecords(): Promise<{
  records: RaceRecord[];
  source: "supabase" | "file";
}> {
  if (isSupabaseConfigured()) {
    try {
      const records = await readRecordsFromSupabase();
      return { records, source: "supabase" };
    } catch {
      // fall through to local file
    }
  }
  return { records: await readRecordsFile(), source: "file" };
}

export async function writeRecords(records: RaceRecord[]): Promise<{
  records: RaceRecord[];
  source: "supabase" | "file";
  path?: string;
}> {
  if (isSupabaseConfigured()) {
    try {
      // replaceRecordsInSupabase 내부에서 기존과 병합
      const saved = await replaceRecordsInSupabase(records);
      try {
        await writeRecordsFile(saved);
      } catch {
        // ignore backup failure
      }
      return { records: saved, source: "supabase" };
    } catch (err) {
      const existing = await readRecordsFile();
      const ordered = sortRecords([...existing, ...records]);
      const filePath = await writeRecordsFile(ordered);
      return {
        records: ordered,
        source: "file",
        path: `${filePath} (supabase 오류: ${String(err)})`,
      };
    }
  }

  const existing = await readRecordsFile();
  const ordered = sortRecords([...existing, ...records]);
  const filePath = await writeRecordsFile(ordered);
  return { records: ordered, source: "file", path: filePath };
}
