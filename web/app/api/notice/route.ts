import { NextResponse } from "next/server";
import { authorizeUpload } from "@/lib/auth";
import { isSupabaseConfigured } from "@/lib/records";
import { readNotice, writeNotice } from "@/lib/notice";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const { notice, source } = await readNotice();
  return NextResponse.json({
    notice,
    source,
    supabaseConfigured: isSupabaseConfigured(),
  });
}

export async function POST(request: Request) {
  if (!authorizeUpload(request)) {
    return NextResponse.json({ error: "수정 권한이 없습니다." }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "JSON 본문이 필요합니다." }, { status: 400 });
  }

  const content = (body as { content?: unknown }).content;
  if (typeof content !== "string") {
    return NextResponse.json(
      { error: "content 문자열이 필요합니다." },
      { status: 400 },
    );
  }

  if (content.length > 2000) {
    return NextResponse.json(
      { error: "공지사항은 2000자 이하여야 합니다." },
      { status: 400 },
    );
  }

  const saved = await writeNotice(content);
  return NextResponse.json({
    ok: true,
    notice: saved.notice,
    source: saved.source,
    path: saved.path,
  });
}
