import { createClient as createBrowserClient } from "@supabase/supabase-js";
import { promises as fs } from "fs";
import path from "path";
import { isSupabaseConfigured } from "@/lib/records";

export type SiteNotice = {
  content: string;
  updated_at: string | null;
};

const DEFAULT_NOTICE: SiteNotice = {
  content: "",
  updated_at: null,
};

function projectDataPath(): string {
  return path.join(process.cwd(), "..", "data", "notice.json");
}

function localFallbackPath(): string {
  return path.join(process.cwd(), "data", "notice.json");
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

function normalizeNotice(raw: Partial<SiteNotice> | null | undefined): SiteNotice {
  const content = String(raw?.content ?? "").trimEnd();
  const updated =
    raw?.updated_at == null || raw.updated_at === ""
      ? null
      : String(raw.updated_at);
  return { content, updated_at: updated };
}

async function readNoticeFile(): Promise<SiteNotice> {
  const candidates = [projectDataPath(), localFallbackPath()];
  for (const file of candidates) {
    try {
      const text = await fs.readFile(file, "utf-8");
      const raw = JSON.parse(text) as Partial<SiteNotice>;
      return normalizeNotice(raw);
    } catch {
      // try next
    }
  }
  return { ...DEFAULT_NOTICE };
}

async function writeNoticeFile(notice: SiteNotice): Promise<string> {
  const payload = JSON.stringify(notice, null, 2);
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

async function readNoticeFromSupabase(): Promise<SiteNotice> {
  const supabase = adminClient();
  const { data, error } = await supabase
    .from("site_notice")
    .select("content,updated_at")
    .eq("id", 1)
    .maybeSingle();

  if (error) throw error;
  if (!data) return { ...DEFAULT_NOTICE };
  return normalizeNotice(data as Partial<SiteNotice>);
}

async function writeNoticeToSupabase(content: string): Promise<SiteNotice> {
  const supabase = adminClient();
  const updated_at = new Date().toISOString();
  const { data, error } = await supabase
    .from("site_notice")
    .upsert(
      { id: 1, content, updated_at },
      { onConflict: "id" },
    )
    .select("content,updated_at")
    .single();

  if (error) throw error;
  return normalizeNotice(data as Partial<SiteNotice>);
}

export async function readNotice(): Promise<{
  notice: SiteNotice;
  source: "supabase" | "file";
}> {
  if (isSupabaseConfigured()) {
    try {
      const notice = await readNoticeFromSupabase();
      return { notice, source: "supabase" };
    } catch {
      // fall through
    }
  }
  return { notice: await readNoticeFile(), source: "file" };
}

export async function writeNotice(content: string): Promise<{
  notice: SiteNotice;
  source: "supabase" | "file";
  path?: string;
}> {
  const cleaned = String(content ?? "").trimEnd();

  if (isSupabaseConfigured()) {
    try {
      const notice = await writeNoticeToSupabase(cleaned);
      try {
        await writeNoticeFile(notice);
      } catch {
        // ignore backup failure
      }
      return { notice, source: "supabase" };
    } catch (err) {
      const notice: SiteNotice = {
        content: cleaned,
        updated_at: new Date().toISOString(),
      };
      const filePath = await writeNoticeFile(notice);
      return {
        notice,
        source: "file",
        path: `${filePath} (supabase 오류: ${String(err)})`,
      };
    }
  }

  const notice: SiteNotice = {
    content: cleaned,
    updated_at: new Date().toISOString(),
  };
  const filePath = await writeNoticeFile(notice);
  return { notice, source: "file", path: filePath };
}
