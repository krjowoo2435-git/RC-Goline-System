import { NextResponse } from "next/server";
import {
  clearAllRecordsStore,
  isSupabaseConfigured,
  normalizeRecord,
  readRecords,
  writeRecords,
  type RaceRecord,
} from "@/lib/records";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function authorizeUpload(request: Request): boolean {
  const expected = process.env.RCGLS_UPLOAD_SECRET?.trim();
  const got = request.headers.get("x-rcgls-upload-secret") || "";
  // 배포(Vercel/production)에서는 시크릿 필수 — 미설정 시 POST 거부
  const isProd =
    process.env.VERCEL === "1" || process.env.NODE_ENV === "production";
  if (!expected) {
    return !isProd;
  }
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

export async function DELETE(request: Request) {
  if (!authorizeUpload(request)) {
    return NextResponse.json({ error: "초기화 권한이 없습니다." }, { status: 401 });
  }

  const cleared = await clearAllRecordsStore();
  return NextResponse.json({
    ok: true,
    count: 0,
    source: cleared.source,
    path: cleared.path,
    records: [],
  });
}
