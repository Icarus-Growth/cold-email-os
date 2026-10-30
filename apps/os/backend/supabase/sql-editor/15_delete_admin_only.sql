-- SQL editor paste 15 of 15: 0016_delete_admin_only.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0016  Only an Owner or Admin can delete a row that deletes other rows
--
-- Before: lock_table's team_all rule lets every team member delete. Deleting a
-- client also deleted all of its work (cards, calls, numbers, documents, forms),
-- because those rows are joined to it with "on delete cascade". A Member could
-- wipe a client's whole history with one call.
--
-- Now: a table that other rows cascade from refuses a delete by a signed-in
-- person who is not an Owner or Admin, with a plain message. Members still
-- read, add and change rows as before. Archive (0010) is still the normal way
-- to take a client out of use; nothing in the OS deletes.
--
--   * delete_admin_only(): the guard. The server (secret key) and the SQL
--     editor are not checked, so delete_examples.sql still works.
--   * guard_delete(tbl): adds the guard to one table. Safe to run twice.
--   * lock_table() now also guards every table the locked table cascades from,
--     so a table made later (an Interview file, a new board) is covered too.
--   * Every table that has one now (clients; documents; flows and
--     campaign_calendars in email marketing) gets the guard below.
-- =============================================================================

create or replace function public.delete_admin_only() returns trigger
language plpgsql set search_path = public as $fn$
begin
  if current_user = 'authenticated' and not public.is_admin() then
    raise exception 'Only an Owner or Admin can delete from %, because it also deletes the work joined to it. Ask an Owner or Admin to archive it instead.',
      tg_table_name using errcode = '42501';
  end if;
  return old;
end
$fn$;
comment on function public.delete_admin_only() is
  'Refuses a delete by a signed-in person who is not an Owner or Admin. On every table other rows cascade from (0016).';

create or replace function public.guard_delete(tbl text) returns void
language plpgsql as $fn$
begin
  execute format('drop trigger if exists %I on public.%I', tbl || '_delete_admin_only', tbl);
  execute format('create trigger %I before delete on public.%I '
                 'for each row execute function public.delete_admin_only()',
                 tbl || '_delete_admin_only', tbl);
end
$fn$;

-- The tables that rows in public.<tbl> cascade from (team has its own rules, 0009).
create or replace function public.cascade_parents(tbl text) returns setof text
language sql stable set search_path = public as $fn$
  select distinct p.relname::text
  from pg_constraint k
  join pg_class p on p.oid = k.confrelid
  where k.contype = 'f' and k.confdeltype = 'c'
    and k.conrelid = format('public.%I', tbl)::regclass
    and p.relnamespace = 'public'::regnamespace
    and p.relname <> 'team';
$fn$;

-- lock_table() as in 0010, and the tables it cascades from get the guard.
create or replace function public.lock_table(tbl text, read_only boolean default false) returns void
language plpgsql as $fn$
declare
  p text;
begin
  if tbl in ('team', 'settings') then
    raise exception 'team and settings have their own rules (0009). Do not run lock_table on them.';
  end if;
  execute format('alter table public.%I enable row level security', tbl);
  execute format('drop policy if exists team_all on public.%I', tbl);
  execute format('drop policy if exists team_read on public.%I', tbl);
  if read_only then
    execute format('create policy team_read on public.%I for select to authenticated '
                   'using ((select public.is_team()))', tbl);
  else
    execute format('create policy team_all on public.%I for all to authenticated '
                   'using ((select public.is_team())) with check ((select public.is_team()))', tbl);
  end if;
  execute format('revoke all on public.%I from anon', tbl);
  if not read_only and tbl not in ('stage_log', 'onboarding_form_drafts') and exists (
    select 1 from pg_attribute
    where attrelid = format('public.%I', tbl)::regclass and attname = 'client_id' and not attisdropped
  ) then
    perform public.add_archive(tbl);
  end if;
  for p in select public.cascade_parents(tbl) loop
    perform public.guard_delete(p);
  end loop;
end
$fn$;

-- Every table that has a cascade now.
do $guard$
declare
  r record;
begin
  for r in
    select distinct p.relname::text as tbl
    from pg_constraint k
    join pg_class p on p.oid = k.confrelid
    where k.contype = 'f' and k.confdeltype = 'c'
      and p.relnamespace = 'public'::regnamespace
      and p.relname <> 'team'
  loop
    perform public.guard_delete(r.tbl);
  end loop;
  perform public.guard_delete('clients');
end
$guard$;

revoke all on function public.guard_delete(text) from public, anon, authenticated;
revoke all on function public.cascade_parents(text) from public, anon, authenticated;
