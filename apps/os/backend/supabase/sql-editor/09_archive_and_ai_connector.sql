-- SQL editor paste 9 of 21: 0010_archive_and_ai_connector.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0010  Archive, the client's Slack channel, and the AI connector
--
-- 1. Archive. Nothing is ever deleted. An archived row has archived_at set.
--    * archived_at is on clients and on every table that holds one client's
--      work (every table with a client_id column, except stage_log and the form
--      drafts). A table made later gets it too, through lock_table().
--    * public.archive_client(id): Owner or Admin only. Archives the client and
--      all of its rows that are not archived yet, all with the same time.
--    * public.restore_client(id): Owner or Admin only. Brings back the client
--      and only the rows that archive_client took (the same time). A card that
--      was archived on its own stays archived.
--    * Only an Owner or Admin can set or clear archived_at, on any table.
--    * The dashboard views leave out archived rows and archived clients
--      (v_open_cards is made per agency type, in 0011).
-- 2. clients.slack_channel_id: the comment now says what it is for.
-- 3. The AI connector (MCP), run by the Modal app with the secret key.
--    * team.mcp_token_hash: a hash of the person's connector token, never the
--      token. No signed-in person can read or write it.
--    * team.mcp_last_seen_at: when the connector last used it. People read it;
--      only the server writes it.
--    * mcp_audit: one row per connector action. Owners and Admins read it.
--      Only the server writes it.
--
-- A new column on team needs its own grant, because team has column grants:
--   grant select (my_column), insert (my_column), update (my_column)
--     on public.team to authenticated;
-- =============================================================================

-- 1. Archive ------------------------------------------------------------------

-- Only an Owner or Admin may set or clear archived_at. Server jobs (the secret
-- key) are not checked.
create or replace function public.archive_admin_only() returns trigger
language plpgsql set search_path = public as $fn$
begin
  if current_user = 'authenticated' and not public.is_admin()
     and ((tg_op = 'INSERT' and new.archived_at is not null)
          or (tg_op = 'UPDATE' and new.archived_at is distinct from old.archived_at)) then
    raise exception 'Only an Owner or Admin can archive or restore.' using errcode = '42501';
  end if;
  return new;
end
$fn$;

-- Give one table archived_at and its guard. Safe to run twice.
create or replace function public.add_archive(tbl text) returns void
language plpgsql as $fn$
begin
  execute format('alter table public.%I add column if not exists archived_at timestamptz', tbl);
  execute format('comment on column public.%I.archived_at is %L', tbl,
                 'When this row was archived. Empty means it is in use. Rows are never deleted.');
  execute format('drop trigger if exists %I on public.%I', tbl || '_archive_admin_only', tbl);
  execute format('create trigger %I before insert or update of archived_at on public.%I '
                 'for each row execute function public.archive_admin_only()',
                 tbl || '_archive_admin_only', tbl);
end
$fn$;

-- The tables that archive_client works on: every table with a client_id column
-- and an archived_at column.
create or replace function public.client_archive_tables() returns setof text
language sql stable set search_path = public as $fn$
  select c.relname::text
  from pg_class c
  where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
    and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'client_id' and not a.attisdropped)
    and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'archived_at' and not a.attisdropped)
  order by 1;
$fn$;

do $arch$
declare t text;
begin
  perform public.add_archive('clients');
  for t in
    select c.relname from pg_class c
    where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
      and c.relname not in ('stage_log', 'onboarding_form_drafts')
      and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'client_id' and not a.attisdropped)
  loop
    perform public.add_archive(t);
  end loop;
end
$arch$;

create or replace function public.archive_client(p_client uuid) returns integer
language plpgsql set search_path = public as $fn$
declare
  t text;
  n integer := 0;
  k integer;
  ts timestamptz := now();
begin
  if current_user = 'authenticated' and not public.is_admin() then
    raise exception 'Only an Owner or Admin can archive a client.' using errcode = '42501';
  end if;
  update public.clients set archived_at = ts where id = p_client and archived_at is null;
  if not found then
    if not exists (select 1 from public.clients where id = p_client) then
      raise exception 'There is no client with that id.' using errcode = 'P0002';
    end if;
    return 0;  -- already archived
  end if;
  for t in select public.client_archive_tables() loop
    execute format('update public.%I set archived_at = $1 where client_id = $2 and archived_at is null', t)
      using ts, p_client;
    get diagnostics k = row_count;
    n := n + k;
  end loop;
  return n;
end
$fn$;
comment on function public.archive_client(uuid) is
  'Owner or Admin only. Archives the client and all its rows that are not archived yet. Returns how many rows (not counting the client).';

create or replace function public.restore_client(p_client uuid) returns integer
language plpgsql set search_path = public as $fn$
declare
  t text;
  n integer := 0;
  k integer;
  ts timestamptz;
begin
  if current_user = 'authenticated' and not public.is_admin() then
    raise exception 'Only an Owner or Admin can restore a client.' using errcode = '42501';
  end if;
  select archived_at into ts from public.clients where id = p_client;
  if not found then
    raise exception 'There is no client with that id.' using errcode = 'P0002';
  end if;
  if ts is null then
    return 0;  -- not archived
  end if;
  update public.clients set archived_at = null where id = p_client;
  for t in select public.client_archive_tables() loop
    execute format('update public.%I set archived_at = null where client_id = $1 and archived_at = $2', t)
      using p_client, ts;
    get diagnostics k = row_count;
    n := n + k;
  end loop;
  return n;
end
$fn$;
comment on function public.restore_client(uuid) is
  'Owner or Admin only. Brings back the client and only the rows archive_client took. Returns how many rows (not counting the client).';

revoke all on function public.archive_client(uuid) from public, anon;
revoke all on function public.restore_client(uuid) from public, anon;
grant execute on function public.archive_client(uuid) to authenticated, service_role;
grant execute on function public.restore_client(uuid) to authenticated, service_role;

-- lock_table() as in 0009, and a new table with a client_id also gets archived_at.
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
  if not read_only and tbl not in ('stage_log', 'onboarding_form_drafts') and exists (
    select 1 from pg_attribute
    where attrelid = format('public.%I', tbl)::regclass and attname = 'client_id' and not attisdropped
  ) then
    perform public.add_archive(tbl);
  end if;
end
$fn$;

-- The dashboard: v_clients_attention leaves out archived clients. (v_stuck_cards,
-- v_late_cards and v_team_load read v_open_cards, which 0011 filters.)
create or replace view public.v_clients_attention with (security_invoker = true) as
with s as (select * from public.settings limit 1),
counts as (
  select c.client_id,
         count(*) filter (where c.stage_changed_at < now() - make_interval(days => (select stuck_after_days from s)))::int as stuck_cards,
         count(*) filter (where c.due_date < current_date)::int as late_cards,
         count(*) filter (where c.stage_number % 10 = 9)::int as sent_back_cards
  from public.v_open_cards c
  where c.client_id is not null
  group by c.client_id
)
select cl.id as client_id,
       cl.client_name,
       cl.account_manager_id,
       cl.onboarding_stage,
       coalesce(k.stuck_cards, 0) as stuck_cards,
       coalesce(k.late_cards, 0) as late_cards,
       coalesce(k.sent_back_cards, 0) as sent_back_cards,
       (cl.onboarding_stage <> '100 - Onboarded'
        and coalesce(cl.onboarding_stage_changed_at, cl.created_at)
            < now() - make_interval(days => (select onboarding_stuck_after_days from s))) as onboarding_stuck,
       (coalesce(k.stuck_cards, 0) + coalesce(k.late_cards, 0) > 0
        or (cl.onboarding_stage <> '100 - Onboarded'
            and coalesce(cl.onboarding_stage_changed_at, cl.created_at)
                < now() - make_interval(days => (select onboarding_stuck_after_days from s)))) as needs_attention
from public.clients cl
left join counts k on k.client_id = cl.id
where cl.status = 'Active' and cl.archived_at is null;
comment on view public.v_clients_attention is 'Active clients (not archived) with stuck or late cards, or onboarding that has not moved.';

-- 2. The client's Slack channel ----------------------------------------------

comment on column public.clients.slack_channel_id is
  'The client''s own Slack channel. The OS never makes or posts in client channels.';

-- 3. The AI connector (MCP) ---------------------------------------------------

alter table public.team add column if not exists mcp_token_hash text unique;
alter table public.team add column if not exists mcp_last_seen_at timestamptz;
comment on column public.team.mcp_token_hash is
  'HMAC-SHA256 of the person''s AI connector token (key: MCP_TOKEN_PEPPER). Never the token. Only the server reads or writes it.';
comment on column public.team.mcp_last_seen_at is 'When this person''s AI connector last made a call. Only the server writes it.';

-- Column grants: a signed-in person reads every team column except the hash,
-- and writes every column except the two connector columns.
do $grants$
declare readable text; writable text;
begin
  select string_agg(quote_ident(attname), ', ' order by attnum) into readable
  from pg_attribute where attrelid = 'public.team'::regclass and attnum > 0 and not attisdropped
    and attname <> 'mcp_token_hash';
  select string_agg(quote_ident(attname), ', ' order by attnum) into writable
  from pg_attribute where attrelid = 'public.team'::regclass and attnum > 0 and not attisdropped
    and attname not in ('mcp_token_hash', 'mcp_last_seen_at');
  revoke all on public.team from anon, authenticated;
  execute format('grant select (%s) on public.team to authenticated', readable);
  execute format('grant insert (%s), update (%s) on public.team to authenticated', writable, writable);
  grant delete on public.team to authenticated;
end
$grants$;

create table if not exists public.mcp_audit (
  id         bigserial primary key,
  team_id    uuid references public.team(id) on delete set null,
  action     text not null,
  args       jsonb,
  ok         boolean not null,
  error      text,
  created_at timestamptz not null default now()
);
comment on table public.mcp_audit is 'One row per AI connector action. Owners and Admins read it. Only the server writes it.';
create index if not exists mcp_audit_team_idx on public.mcp_audit (team_id, created_at desc);

alter table public.mcp_audit enable row level security;
drop policy if exists admin_read on public.mcp_audit;
create policy admin_read on public.mcp_audit for select to authenticated
  using ((select public.is_admin()));
revoke all on public.mcp_audit from anon, authenticated;
grant select on public.mcp_audit to authenticated;
revoke all on sequence public.mcp_audit_id_seq from anon, authenticated;

revoke all on function public.add_archive(text) from public, anon, authenticated;
