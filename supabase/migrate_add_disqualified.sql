-- 기록 말소(DQ) 표시용 컬럼 추가
-- Supabase SQL Editor에서 실행하세요.

alter table public.race_records
  add column if not exists disqualified boolean not null default false;
