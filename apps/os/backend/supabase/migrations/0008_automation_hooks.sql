-- =============================================================================
-- 0008  Automation hooks: the database tells the Modal app when something happens
--
-- Two moments call the OS's automations (apps/os/automations/app.py):
--   * a stage log row is written (a card is added or moves)  -> POST /stage-change
--   * a client is added                                      -> POST /new-client
-- A submitted onboarding form is NOT a hook here: the form app's server calls
-- POST /form-submitted itself, so each form is posted once.
--
-- The calls go out through pg_net after the change is saved, so they never slow
-- down or block a card move. A failed call is only a warning in the database log.
--
-- The Modal address and the shared secret live in Supabase Vault, never in a
-- table. Until tab 3 stores them, every hook does nothing. To store or change them
-- (tab 3 does this with apps/os/automations/connect_db.py):
--   select public.set_automation_hook('https://<your app>-web.modal.run', '<secret>');
-- To switch every hook off:
--   select public.set_automation_hook('', '');
-- =============================================================================

-- pg_net sends the calls. It is on every Supabase project; elsewhere this is skipped.
do $ext$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_net') then
    create extension if not exists pg_net;
  end if;
end
$ext$;

-- Send one call to the Modal app. Returns the request number, or null when the
-- hook is not set up yet. Server only: nobody signed in to the OS can run it.
create or replace function public.call_automation(path text, body jsonb) returns bigint
language plpgsql security definer set search_path = public as $fn$
declare
  base   text;
  secret text;
  req    bigint;
begin
  if to_regclass('vault.decrypted_secrets') is null or to_regnamespace('net') is null then
    return null;
  end if;
  execute $q$
    select max(decrypted_secret) filter (where name = 'os_automations_url'),
           max(decrypted_secret) filter (where name = 'os_shared_secret')
    from vault.decrypted_secrets
    where name in ('os_automations_url', 'os_shared_secret')
  $q$ into base, secret;
  if coalesce(base, '') = '' or coalesce(secret, '') = '' then
    return null;
  end if;
  execute 'select net.http_post(url := $1, body := $2, headers := $3, timeout_milliseconds := 30000)'
    into req
    using rtrim(base, '/') || path,
          body,
          jsonb_build_object('Content-Type', 'application/json', 'X-OS-Secret', secret);
  return req;
exception when others then
  raise warning 'automation call % skipped: %', path, sqlerrm;
  return null;
end
$fn$;
comment on function public.call_automation(text, jsonb) is
  'Sends one call to the OS automations (Modal). Reads the address and the secret from Vault. Does nothing until tab 3 stores them.';

-- Store (or change) the Modal address and the shared secret in Vault.
create or replace function public.set_automation_hook(url text, secret text) returns text
language plpgsql security definer set search_path = public as $fn$
declare
  k   text;
  v   text;
  sid uuid;
begin
  if to_regclass('vault.secrets') is null then
    raise exception 'Vault is not on in this project. Turn it on in Database -> Extensions (supabase_vault).';
  end if;
  foreach k in array array['os_automations_url', 'os_shared_secret'] loop
    v := case when k = 'os_automations_url' then coalesce(url, '') else coalesce(secret, '') end;
    execute 'select id from vault.secrets where name = $1' into sid using k;
    if sid is null then
      execute 'select vault.create_secret($1, $2, $3)' using v, k, 'Used by the OS automations (0008_automation_hooks).';
    else
      execute 'select vault.update_secret($1, $2)' using sid, v;
    end if;
  end loop;
  return case when coalesce(url, '') = '' then 'Hooks off' else 'Hooks on' end;
end
$fn$;
comment on function public.set_automation_hook(text, text) is
  'Stores the Modal address and the shared secret in Vault. Empty values switch every hook off.';

revoke all on function public.call_automation(text, jsonb) from public, anon, authenticated;
revoke all on function public.set_automation_hook(text, text) from public, anon, authenticated;

-- The two hooks --------------------------------------------------------------
create or replace function public.hook_stage_change() returns trigger
language plpgsql security definer set search_path = public as $fn$
begin
  perform public.call_automation('/stage-change', to_jsonb(new));
  return null;
end
$fn$;

create or replace function public.hook_new_client() returns trigger
language plpgsql security definer set search_path = public as $fn$
begin
  perform public.call_automation('/new-client', jsonb_build_object('id', new.id));
  return null;
end
$fn$;

drop trigger if exists stage_log_hook on public.stage_log;
create trigger stage_log_hook after insert on public.stage_log
  for each row execute function public.hook_stage_change();

drop trigger if exists clients_hook on public.clients;
create trigger clients_hook after insert on public.clients
  for each row execute function public.hook_new_client();
