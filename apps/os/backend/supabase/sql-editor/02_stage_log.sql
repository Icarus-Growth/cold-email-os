-- SQL editor paste 2 of 15: 0002_stage_log.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0002  The stage log
--
-- One row for every new card and every stage change, on every board.
-- The database writes it by itself, so nothing can move without a record.
-- It feeds the dashboard ("what is stuck") and the Slack alerts (tab 3).
--
-- Every board table has three columns the trigger fills:
--   <stage column>, stage_changed_at, stage_changed_by_id
-- The clients table uses onboarding_stage, onboarding_stage_changed_at and
-- onboarding_stage_changed_by_id.
--
-- To give a new board a log:   select public.attach_stage_log('my_table');
-- (for a stage column with another name: attach_stage_log('my_table', 'my_col'))
-- =============================================================================

create table public.stage_log (
  id             bigserial primary key,
  board          text        not null,
  record_id      uuid        not null,
  record_name    text,
  client_id      uuid,
  from_stage     text,
  to_stage       text        not null,
  changed_at     timestamptz not null default now(),
  changed_by_id  uuid references public.team(id) on delete set null,
  is_example     boolean     not null default false
);
create index stage_log_record_idx on public.stage_log (board, record_id, changed_at desc);
create index stage_log_changed_at_idx on public.stage_log (changed_at desc);
comment on table public.stage_log is
  'One row per new card and per stage change, on every board. Written by the database itself. from_stage is empty for a new card.';

-- The team row of the person who is signed in (empty for server jobs).
create or replace function public.current_team_id() returns uuid
language sql stable security definer set search_path = public as $fn$
  select id from public.team
  where email = lower(coalesce(auth.jwt() ->> 'email', ''))
  limit 1;
$fn$;

-- The trigger. TG_ARGV[0] is the stage column. The "changed at" and
-- "changed by" columns are named after it.
create or replace function public.log_stage_change() returns trigger
language plpgsql security definer set search_path = public as $fn$
declare
  col      text := tg_argv[0];
  prefix   text := case when col = 'stage' then 'stage' else col end;
  row_new  jsonb := to_jsonb(new);
  row_old  jsonb := case when tg_op = 'UPDATE' then to_jsonb(old) else '{}'::jsonb end;
  before_v text := row_old ->> col;
  after_v  text := row_new ->> col;
  mover    uuid;
  name_v   text;
begin
  if tg_op = 'UPDATE' and before_v is not distinct from after_v then
    return new;
  end if;

  -- Who moved it: the writer may say so in the same statement; otherwise the
  -- signed-in person. An old "changed by" left on the row is never reused.
  if (row_new ->> (prefix || '_changed_by_id')) is distinct from (row_old ->> (prefix || '_changed_by_id')) then
    mover := (row_new ->> (prefix || '_changed_by_id'))::uuid;
  end if;
  mover := coalesce(mover, public.current_team_id());
  new := jsonb_populate_record(new, jsonb_build_object(
           prefix || '_changed_at', now(),
           prefix || '_changed_by_id', mover));

  -- The card's name: the first column ending in _name or _title.
  select value into name_v from jsonb_each_text(row_new)
  where key ~ '(_name|_title)$' and key not like '%_by_name' order by key limit 1;

  insert into public.stage_log (board, record_id, record_name, client_id, from_stage, to_stage, changed_by_id, is_example)
  values (tg_table_name,
          (row_new ->> 'id')::uuid,
          name_v,
          case when tg_table_name = 'clients' then (row_new ->> 'id')::uuid
               else (row_new ->> 'client_id')::uuid end,
          before_v,
          after_v,
          mover,
          coalesce((row_new ->> 'is_example')::boolean, false));
  return new;
end
$fn$;
comment on function public.log_stage_change() is
  'Fills <stage>_changed_at and <stage>_changed_by_id and writes one stage_log row when a card is added or its stage moves.';

create or replace function public.attach_stage_log(tbl text, col text default 'stage') returns void
language plpgsql as $fn$
begin
  execute format('drop trigger if exists %I on public.%I', tbl || '_log_stage', tbl);
  execute format('create trigger %I before insert or update of %I on public.%I '
                 'for each row execute function public.log_stage_change(%L)',
                 tbl || '_log_stage', col, tbl, col);
end
$fn$;

select public.attach_stage_log('tasks');
select public.attach_stage_log('clients', 'onboarding_stage');
