-- 공개 anon 쓰기 정책 제거 (웹 API + service role 권장)
-- Dashboard → SQL Editor 에서 실행.

drop policy if exists "Anyone can insert race_records" on public.race_records;
drop policy if exists "Anyone can update race_records" on public.race_records;
drop policy if exists "Anyone can delete race_records" on public.race_records;

notify pgrst, 'reload schema';
