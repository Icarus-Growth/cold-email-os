-- SQL editor paste 20 of 21: 0021_sending_and_lead_tables.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0021  Cold email: the tables the sending and lead skills work in
--
-- Sending set-up (skills/fulfilment/sending-*): one Inbox set-ups card
-- (inbox_batches) holds the domains bought for it, and each domain holds its
-- inboxes.
--   * sending_domains: one sending domain, from planned to ready.
--   * sending_inboxes: one inbox on one domain, from planned to ready.
-- Lead lists (google-maps-scraper, website-classifier, email-guesser,
-- catch-all-verifier, tam-mapper):
--   * lead_searches: one search (keyword + location) to run for a client.
--   * lead_companies: one company found, and whether it fits the client.
--   * lead_contacts: one person at a company, and their checked email.
-- None of them is a board. The skills fill them; people read them.
--
-- Every table: team only, archived with its client, safe from a Member delete
-- where other rows hang off it (0016: sending_domains, lead_companies, and
-- inbox_batches, because its domains and inboxes go with it).
-- clients.sending_domains (0004, a plain list of names) stays.
-- =============================================================================

-- 1. Sending domains -------------------------------------------------------------
create table public.sending_domains (
  id                  uuid primary key default gen_random_uuid(),
  batch_id            uuid not null references public.inbox_batches(id) on delete cascade,
  client_id           uuid not null references public.clients(id) on delete cascade,
  domain              text not null,
  inbox_kind          text check (inbox_kind in ('google', 'outlook')),
  inbox_provider      text,
  registrar           text,
  name_style          text,
  planned_price_usd   numeric(10,2),
  paid_price_usd      numeric(10,2),
  inboxes_planned     int,
  warm_days           int default 14,
  status              text not null default 'planned'
                      check (status in ('planned', 'bought', 'ordered', 'nameservers_set', 'inboxes_active',
                                        'dns_verified', 'warming', 'ready')),
  provider_ref        text,
  nameservers         text[],
  forward_to          text,
  waiting_for         text,
  next_check_at       timestamptz,
  last_error          text,
  last_note           text,
  checked_at          timestamptz,
  step_started_at     timestamptz,
  bought_at           timestamptz,
  dns_verified_at     timestamptz,
  warmup_started_at   timestamptz,
  ready_at            timestamptz,
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.sending_domains is 'One sending domain bought for one Inbox set-ups card, from planned to ready. Filled by the sending skills.';
comment on column public.sending_domains.status is 'Where the set-up is: planned, bought, ordered, nameservers_set, inboxes_active, dns_verified, warming, ready.';
comment on column public.sending_domains.inbox_provider is 'The tool that hosts the inboxes, as a value (not a column per tool).';
comment on column public.sending_domains.provider_ref is 'The order or account number at the inbox provider. Never a login or a key.';
comment on column public.sending_domains.waiting_for is 'What the next step waits for, in plain words (for example DNS to spread).';
comment on column public.sending_domains.next_check_at is 'When the daily run looks at this domain again.';
create unique index sending_domains_domain_key on public.sending_domains (lower(domain));
create index sending_domains_batch_idx on public.sending_domains (batch_id);
create index sending_domains_status_idx on public.sending_domains (status);

-- 2. Sending inboxes -------------------------------------------------------------
create table public.sending_inboxes (
  id                  uuid primary key default gen_random_uuid(),
  domain_id           uuid not null references public.sending_domains(id) on delete cascade,
  batch_id            uuid not null references public.inbox_batches(id) on delete cascade,
  client_id           uuid not null references public.clients(id) on delete cascade,
  address             text not null,
  first_name          text,
  last_name           text,
  inbox_kind          text,
  status              text not null default 'planned'
                      check (status in ('planned', 'ordered', 'active', 'warming', 'ready')),
  warmup_tool         text,
  warmup_account_id   text,
  warmup_daily_limit  int,
  warmup_started_at   timestamptz,
  ready_at            timestamptz,
  last_error          text,
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.sending_inboxes is 'One inbox on one sending domain, from planned to ready. Filled by the sending skills. Never holds a password.';
comment on column public.sending_inboxes.warmup_tool is 'The warm-up tool, as a value (not a column per tool).';
comment on column public.sending_inboxes.warmup_account_id is 'The inbox''s number in the warm-up tool. Never a login or a key.';
create unique index sending_inboxes_address_key on public.sending_inboxes (lower(address));
create index sending_inboxes_batch_idx on public.sending_inboxes (batch_id);
create index sending_inboxes_domain_idx on public.sending_inboxes (domain_id);

-- 3. Lead searches ---------------------------------------------------------------
create table public.lead_searches (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references public.clients(id) on delete cascade,
  campaign_id         uuid references public.campaigns(id) on delete set null,
  keyword             text not null,
  location            text not null,
  industry            text,
  segment             text,
  status              text not null default 'to do' check (status in ('to do', 'done', 'failed')),
  attempts            int not null default 0,
  results_count       int,
  new_count           int,
  credits_used        int not null default 0,
  error               text,
  searched_at         timestamptz,
  archived_at         timestamptz,
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.lead_searches is 'One map search (keyword and location) to run for one client. The scraper runs the "to do" ones.';
comment on column public.lead_searches.new_count is 'Companies this search found that were not in the list yet.';
create unique index lead_searches_key on public.lead_searches (client_id, lower(keyword), lower(location));
create index lead_searches_client_status_idx on public.lead_searches (client_id, status);

-- 4. Lead companies --------------------------------------------------------------
create table public.lead_companies (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references public.clients(id) on delete cascade,
  search_id           uuid references public.lead_searches(id) on delete set null,
  campaign_id         uuid references public.campaigns(id) on delete set null,
  company_name        text not null,
  website             text,
  domain              text,
  phone               text,
  address             text,
  location            text,
  category            text,
  industry            text,
  segment             text,
  size_band           text,
  place_id            text,
  rating              numeric(3,2),
  review_count        int,
  source              text,
  fit_status          text check (fit_status in ('fit', 'not fit', 'unsure', 'error')),
  fit_confidence      int,
  fit_reason          text,
  fit_evidence        text,
  fit_method          text,
  fit_checked_at      timestamptz,
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.lead_companies is 'One company found for one client, and whether it fits the client''s market. Filled by the lead skills.';
comment on column public.lead_companies.place_id is 'The map listing''s own id, so a company is never added twice.';
comment on column public.lead_companies.fit_status is 'fit, not fit, unsure, or error. Empty until the website check has run.';
create unique index lead_companies_place_key on public.lead_companies (client_id, place_id) where place_id is not null;
create unique index lead_companies_domain_key on public.lead_companies (client_id, lower(domain)) where domain is not null;
create index lead_companies_fit_idx on public.lead_companies (client_id, fit_status);
create index lead_companies_unchecked_idx on public.lead_companies (client_id) where fit_checked_at is null;

-- 5. Lead contacts ---------------------------------------------------------------
create table public.lead_contacts (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references public.clients(id) on delete cascade,
  company_id          uuid references public.lead_companies(id) on delete cascade,
  full_name           text,
  first_name          text,
  last_name           text,
  title               text,
  linkedin_url        text,
  domain              text,
  email               text,
  email_status        text check (email_status in ('valid', 'risky', 'catch-all', 'invalid', 'none', 'skipped', 'unknown')),
  email_score         int,
  email_evidence      text,
  email_source        text,
  email_pattern       text,
  email_candidates    jsonb,
  catch_all           boolean,
  guess_credits       int not null default 0,
  guess_checked_at    timestamptz,
  deep_status         text,
  deep_credits        int not null default 0,
  deep_checked_at     timestamptz,
  final_verdict       text,
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.lead_contacts is 'One person at a lead company, and their email as checked by the email skills.';
comment on column public.lead_contacts.email_status is 'valid, risky, catch-all (the deep check runs next), invalid, none (no address works), skipped (nothing to check) or unknown. Written by the email skills.';
comment on column public.lead_contacts.catch_all is 'True when the company''s mail server accepts every address, so a plain check cannot tell.';
comment on column public.lead_contacts.final_verdict is 'The last word on the email after every check, in a few words.';
create index lead_contacts_client_idx on public.lead_contacts (client_id);
create index lead_contacts_company_idx on public.lead_contacts (company_id);
create index lead_contacts_unguessed_idx on public.lead_contacts (client_id) where guess_checked_at is null;
create index lead_contacts_deep_todo_idx on public.lead_contacts (client_id) where catch_all and deep_checked_at is null;

-- Every table: updated_at, team only, archive (0010), delete guard on the parents (0016).
do $t$
declare t text;
begin
  foreach t in array array['sending_domains', 'sending_inboxes', 'lead_searches', 'lead_companies', 'lead_contacts'] loop
    execute format('create trigger %I before update on public.%I for each row execute function public.touch_updated_at()',
                   t || '_touch_updated_at', t);
    perform public.lock_table(t);
  end loop;
end
$t$;
