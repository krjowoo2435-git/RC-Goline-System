-- RC Goal Line — 웹/데스크톱 공유 기록
-- Supabase Dashboard → SQL Editor 에서 실행하세요.

create table if not exists public.race_records (
  id bigint generated always as identity primary key,
  student_id text not null,
  rc_id text not null default '',
  name text not null default '',
  rank integer not null default 0,
  lap1 text not null default '--:--:---',
  lap2 text not null default '--:--:---',
  lap3 text not null default '--:--:---',
  total text not null default '--:--:---',
  total_ms integer not null default 0,
  penalty_ms double precision not null default 0,
  updated_at timestamptz not null default now(),
  constraint race_records_student_id_key unique (student_id)
);

create index if not exists race_records_rank_idx
  on public.race_records (rank asc);

create index if not exists race_records_total_ms_idx
  on public.race_records (total_ms asc);

alter table public.race_records enable row level security;

drop policy if exists "Anyone can read race_records" on public.race_records;
create policy "Anyone can read race_records"
  on public.race_records
  for select
  to anon, authenticated
  using (true);

-- 경기장 키오스크용: 데스크톱/웹 API가 publishable key 로 업로드
-- (서비스 롤 키 없이 동작). 공개 배포 시 서비스 롤 + UPLOAD_SECRET 로 강화하세요.
drop policy if exists "Anyone can insert race_records" on public.race_records;
create policy "Anyone can insert race_records"
  on public.race_records
  for insert
  to anon, authenticated
  with check (true);

drop policy if exists "Anyone can update race_records" on public.race_records;
create policy "Anyone can update race_records"
  on public.race_records
  for update
  to anon, authenticated
  using (true)
  with check (true);

drop policy if exists "Anyone can delete race_records" on public.race_records;
create policy "Anyone can delete race_records"
  on public.race_records
  for delete
  to anon, authenticated
  using (true);

notify pgrst, 'reload schema';
