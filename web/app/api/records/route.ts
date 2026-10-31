import { NextResponse } from "next/server";
import {
  isSupabaseConfigured,
  normalizeRecord,
  readRecords,
  writeRecords,
  type RaceRecord,
} from "@/lib/records";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function authorizeUpload(request: Request): boolean {
  const expected = process.env.RCGLS_UPLOAD_SECRET;
  if (!expected) return true; // 시크릿 미설정 시 허용 (로컬/경기장)
  const got = request.headers.get("x-rcgls-upload-secret") || "";
  return got === expected;
}

export async function GET() {
  const { records, source } = await readRecords();
  return NextResponse.json({
    records,
    source,
    supabaseConfigured: isSupabaseConfigured(),
  });
}

export async function POST(request: Request) {
  if (!authorizeUpload(request)) {
    return NextResponse.json({ error: "업로드 권한이 없습니다." }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "JSON 본문이 필요합니다." }, { status: 400 });
  }

  const payload = body as { records?: unknown };
  if (!Array.isArray(payload.records)) {
    return NextResponse.json({ error: "records 배열이 필요합니다." }, { status: 400 });
  }

  const records: RaceRecord[] = payload.records.map((item) =>
    normalizeRecord(item as Partial<RaceRecord> & Record<string, unknown>),
  );

  const saved = await writeRecords(records);
  return NextResponse.json({
    ok: true,
    count: saved.records.length,
    source: saved.source,
    path: saved.path,
    records: saved.records,
  });
}
