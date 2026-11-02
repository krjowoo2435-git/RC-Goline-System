export function normalizeSecret(raw: string | undefined | null): string {
  let s = (raw ?? "").trim();
  if (
    s.length >= 2 &&
    ((s.startsWith('"') && s.endsWith('"')) ||
      (s.startsWith("'") && s.endsWith("'")))
  ) {
    s = s.slice(1, -1).trim();
  }
  return s;
}

/** RCGLS_UPLOAD_SECRET 헤더 검증. 프로덕션에서는 시크릿 미설정 시 거부. */
export function authorizeUpload(request: Request): boolean {
  const expected = normalizeSecret(process.env.RCGLS_UPLOAD_SECRET);
  const got = normalizeSecret(request.headers.get("x-rcgls-upload-secret"));
  const isProd =
    process.env.VERCEL === "1" || process.env.NODE_ENV === "production";
  if (!expected) {
    return !isProd;
  }
  return got === expected;
}
