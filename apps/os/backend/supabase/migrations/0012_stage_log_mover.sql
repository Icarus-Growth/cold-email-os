-- =============================================================================
-- 0012  The stage log keeps "moved by" when the same person moves twice
--
-- Before: a move that named its mover (stage_changed_by_id in the same change,
-- as the AI connector does) was only believed when the name differed from the
-- one already on the row. The same person moving the same card twice in a row
-- left "moved by" empty, because the connector has no sign-in to fall back on.
--
-- Now: a second trigger, <table>_log_mover, fires only when the change itself
-- names the "changed by" column. It marks the row, and log_stage_change takes
-- the named mover, the same person or not. A change that does not name it
-- (the app) still records the signed-in person, and an old name left on the
-- row is still never reused.
--
-- The call does not change: one update that sets the stage and
-- <stage>_changed_by_id together.
--
-- attach_stage_log() now adds both triggers. Every board that already has a
-- log gets the new one below. Safe to run twice.
-- =============================================================================

-- Fires before <table>_log_stage (triggers run in name order). It runs only
-- when the change names the "changed by" column and the stage moves. The mark
-- is a "changed at" of -infinity, which log_stage_change always overwrites.
create or replace function public.mark_stage_mover() returns trigger
language plpgsql set search_path = public as $fn$
declare
  col     text := tg_argv[0];
  row_new jsonb := to_jsonb(new);
begin
  if (row_new ->> col) is distinct from (to_jsonb(old) ->> col) then
    new := jsonb_populate_record(new, jsonb_build_object(col || '_changed_at', '-infinity'));
  end if;
  return new;
end
$fn$;
comment on function public.mark_stage_mover() is
  'Marks a stage move whose change names <stage>_changed_by_id, so log_stage_change takes that mover even when it is the same person as last time.';

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

  -- Who moved it: the writer may say so in the same change (a new card, or a
  -- move marked by <table>_log_mover); otherwise the signed-in person. An old
  -- "changed by" left on the row is never reused.
  if tg_op = 'INSERT' or (row_new ->> (prefix || '_changed_at')) = '-infinity' then
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
  execute format('drop trigger if exists %I on public.%I', tbl || '_log_mover', tbl);
  execute format('create trigger %I before update of %I on public.%I '
                 'for each row execute function public.mark_stage_mover(%L)',
                 tbl || '_log_mover', col || '_changed_by_id', tbl, col);
end
$fn$;

-- Every board that already has a log (the core boards, the type boards and
-- any board added since) gets the new trigger.
do $do$
declare
  r record;
begin
  for r in
    select c.relname::text as tbl,
           substring(pg_get_triggerdef(t.oid) from 'log_stage_change\(''([^'']+)''\)') as col
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    where c.relnamespace = 'public'::regnamespace
      and t.tgfoid = 'public.log_stage_change'::regproc
      and not t.tgisinternal
  loop
    perform public.attach_stage_log(r.tbl, r.col);
  end loop;
end
$do$;
