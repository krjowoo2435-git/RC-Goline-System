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
};

const EMPTY_LAP = "--:--:---";

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

export function normalizeRecord(
  raw: Partial<RaceRecord> & Record<string, unknown>,
): RaceRecord {
  const lapsRaw = Array.isArray(raw.laps)
    ? raw.laps.map(String)
    : [raw.lap1, raw.lap2, raw.lap3].map((v) =>
        v == null || v === "" ? EMPTY_LAP : String(v),
      );
  const laps = [...lapsRaw];
  while (laps.length < 3) laps.push(EMPTY_LAP);

  return {
    rank: Number(raw.rank) || 0,
    rc_id: String(raw.rc_id ?? ""),
    student_id: String(raw.student_id ?? ""),
    name: String(raw.name ?? ""),
    laps: laps.slice(0, 3),
    total: String(raw.total ?? EMPTY_LAP),
    total_ms: Number(raw.total_ms) || 0,
    penalty_ms: Number(raw.penalty_ms) || 0,
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
  });
}

function sortRecords(records: RaceRecord[]): RaceRecord[] {
  return [...records]
    .map(normalizeRecord)
    .filter((r) => r.student_id)
    .sort((a, b) => (a.total_ms || 1e12) - (b.total_ms || 1e12))
    .map((row, i) => ({ ...row, rank: i + 1 }));
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

export async function readRecordsFromSupabase(): Promise<RaceRecord[]> {
  const supabase = adminClient();
  const { data, error } = await supabase
    .from("race_records")
    .select(
      "student_id,rc_id,name,rank,lap1,lap2,lap3,total,total_ms,penalty_ms",
    )
    .order("rank", { ascending: true });

  if (error) throw error;
  return sortRecords((data as DbRow[] | null)?.map(fromDbRow) ?? []);
}

export async function replaceRecordsInSupabase(
  records: RaceRecord[],
): Promise<RaceRecord[]> {
  const ordered = sortRecords(records);
  const supabase = adminClient();

  const { error: delError } = await supabase
    .from("race_records")
    .delete()
    .neq("student_id", "");
  if (delError) throw delError;

  if (ordered.length === 0) return [];

  const { data, error } = await supabase
    .from("race_records")
    .insert(ordered.map(toDbRow))
    .select(
      "student_id,rc_id,name,rank,lap1,lap2,lap3,total,total_ms,penalty_ms",
    );

  if (error) throw error;
  return sortRecords((data as DbRow[] | null)?.map(fromDbRow) ?? ordered);
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
  const ordered = sortRecords(records);

  if (isSupabaseConfigured()) {
    try {
      const saved = await replaceRecordsInSupabase(ordered);
      // 로컬 백업도 유지
      try {
        await writeRecordsFile(saved);
      } catch {
        // ignore backup failure
      }
      return { records: saved, source: "supabase" };
    } catch (err) {
      // Supabase 실패 시 로컬로 폴백
      const filePath = await writeRecordsFile(ordered);
      return {
        records: ordered,
        source: "file",
        path: `${filePath} (supabase 오류: ${String(err)})`,
      };
    }
  }

  const filePath = await writeRecordsFile(ordered);
  return { records: ordered, source: "file", path: filePath };
}
