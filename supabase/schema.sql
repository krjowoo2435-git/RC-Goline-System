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
  disqualified boolean not null default false,
  updated_at timestamptz not null default now(),
  -- 학번+이름으로 동일 선수 판별 (성적 저하 시 미갱신)
  constraint race_records_student_name_key unique (student_id, name)
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

-- 쓰기는 웹 API(서비스 롤 권장) + RCGLS_UPLOAD_SECRET 으로만 허용하세요.
-- anon 직접 insert/update/delete 는 공개 배포에서 위험하므로 기본 비활성.
drop policy if exists "Anyone can insert race_records" on public.race_records;
drop policy if exists "Anyone can update race_records" on public.race_records;
drop policy if exists "Anyone can delete race_records" on public.race_records;

-- 로컬/키오스크에서 publishable(anon) 키로 직접 쓸 때만 아래를 다시 활성화하세요.
-- create policy "Anyone can insert race_records" ...

notify pgrst, 'reload schema';
