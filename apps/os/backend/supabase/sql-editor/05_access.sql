-- SQL editor paste 5 of 21: 0005_access.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0005  Team-only access
--
-- Only a signed-in person who is on the team table, Active, with can_sign_in
-- ticked, can see or change any row. Everyone else sees nothing:
--   * the publishable key alone (not signed in) gets nothing;
--   * a login that is not on the team list gets nothing.
-- Server jobs use the secret key, which skips these rules, so they still work.
--
-- Every new table must be locked the same way:   select public.lock_table('my_table');
-- Every new view must read with the rights of the person asking:
--   create view ... with (security_invoker = true) as ...
-- =============================================================================

create or replace function public.is_team() returns boolean
language sql stable security definer set search_path = public as $fn$
  select exists (
    select 1 from public.team
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
      and status = 'Active'
      and can_sign_in
  );
$fn$;
comment on function public.is_team() is 'True only for a signed-in, Active team member with can_sign_in ticked.';

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $fn$
  select exists (
    select 1 from public.team
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
      and status = 'Active'
      and can_sign_in
      and access in ('Owner', 'Admin')
  );
$fn$;
comment on function public.is_admin() is 'True only for an Owner or Admin. Used by the "add team member" step.';

revoke all on function public.is_team() from public, anon;
revoke all on function public.is_admin() from public, anon;
grant execute on function public.is_team() to authenticated;
grant execute on function public.is_admin() to authenticated;

-- Lock one table: row level security on, one team-only policy, nothing for anon.
create or replace function public.lock_table(tbl text, read_only boolean default false) returns void
language plpgsql as $fn$
begin
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
end
$fn$;

-- Lock every table that exists now.
do $lock$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    if t = 'onboarding_form_drafts' then
      -- Server only: row level security on, and no policy for anyone.
      execute 'alter table public.onboarding_form_drafts enable row level security';
      execute 'revoke all on public.onboarding_form_drafts from anon, authenticated';
    elsif t = 'stage_log' then
      -- The database writes it; people only read it.
      perform public.lock_table(t, true);
    else
      perform public.lock_table(t);
    end if;
  end loop;
end
$lock$;

revoke usage, select on all sequences in schema public from anon;
