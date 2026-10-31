-- 기존 테이블이 student_id 단독 unique 인 경우 실행
-- Supabase SQL Editor에서 실행하세요.

alter table public.race_records
  drop constraint if exists race_records_student_id_key;

alter table public.race_records
  drop constraint if exists race_records_student_name_key;

alter table public.race_records
  add constraint race_records_student_name_key unique (student_id, name);
