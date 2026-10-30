-- SQL editor paste 8 of 15: 0009_team_admin_only.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0009  Only an Owner or Admin can change who is on the team
--
-- Before this, the team and settings tables had the same rule as every other
-- table: any team member could change any row. So a Member could make themselves
-- Owner, or tick "can sign in" for someone, or change the agency settings.
--
-- Now:
--   * Everyone on the team can still read both tables.
--   * Only an Owner or Admin (public.is_admin()) can add or remove a person, or
--     change any field on anyone, and only they can change the settings row.
--   * A Member can change their own row only (their email is their sign-in email),
--     and only these fields: full_name, job_title, phone, slack_user_id.
--     A change to any other field (access, can_sign_in, status, email, capacity,
--     notes, ...) is refused with an error.
-- Server jobs use the secret key, which skips these rules, so they still work.
--
-- Never run lock_table() on team or settings: it would put back the old rule.
-- lock_table() now refuses these two tables.
-- =============================================================================

-- The team table.
drop policy if exists team_all on public.team;
drop policy if exists team_read on public.team;
drop policy if exists admin_all on public.team;
drop policy if exists self_update on public.team;

create policy team_read on public.team for select to authenticated
  using ((select public.is_team()));
create policy admin_all on public.team for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
create policy self_update on public.team for update to authenticated
  using ((select public.is_team()) and email = lower(coalesce(auth.jwt() ->> 'email', '')))
  with check ((select public.is_team()) and email = lower(coalesce(auth.jwt() ->> 'email', '')));

-- A row rule cannot name fields, so this check does: a signed-in person who is
-- not an Owner or Admin may change only their name fields.
create or replace function public.team_member_fields_only() returns trigger
language plpgsql set search_path = public as $fn$
declare
  own_fields text[] := array['full_name', 'job_title', 'phone', 'slack_user_id', 'updated_at'];
begin
  if current_user = 'authenticated' and not public.is_admin()
     and (to_jsonb(new) - own_fields) is distinct from (to_jsonb(old) - own_fields) then
    raise exception 'Only an Owner or Admin can change that. You can change your own name, job title, phone and Slack user ID.'
      using errcode = '42501';
  end if;
  return new;
end
$fn$;

drop trigger if exists team_member_fields_only on public.team;
create trigger team_member_fields_only before update on public.team
  for each row execute function public.team_member_fields_only();

-- The settings row.
drop policy if exists team_all on public.settings;
drop policy if exists team_read on public.settings;
drop policy if exists admin_all on public.settings;

create policy team_read on public.settings for select to authenticated
  using ((select public.is_team()));
create policy admin_all on public.settings for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));

-- lock_table() as in 0005, but it refuses team and settings.
create or replace function public.lock_table(tbl text, read_only boolean default false) returns void
language plpgsql as $fn$
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
end
$fn$;
