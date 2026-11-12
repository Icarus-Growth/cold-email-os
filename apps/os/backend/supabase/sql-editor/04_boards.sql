-- SQL editor paste 4 of 19: 0004_boards.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0004  Boards: cold email
--
-- Boards on the Tasks screen: Tasks (made in 0001) and Campaigns.
-- inbox_batches has a ladder but no board. It shows as a list on the client page.
-- =============================================================================

-- Cold email columns on the client (wide-table rule) -------------------------
alter table public.clients
  add column campaign_manager_id uuid references public.team(id) on delete set null,
  add column target_market       text,
  add column offer_doc_url       text,
  add column copy_doc_url        text,
  add column sending_domains     text;
comment on column public.clients.target_market is 'Who the client sells to, in a few words.';
comment on column public.clients.sending_domains is 'The domains bought for sending, comma separated. Names only, never logins.';

-- Campaigns board -------------------------------------------------------------
create type public.campaign_stage as enum (
  '0 - Backlog',
  '10 - List Building',
  '20 - Copywriting',
  '29 - Copy Amendments',
  '30 - Client Review',
  '39 - Client Changes',
  '40 - Ready To Launch',
  '50 - Live',
  '100 - Ended'
);
create type public.campaign_channel as enum ('Email');

create table public.campaigns (
  id                   uuid primary key default gen_random_uuid(),
  campaign_name        text not null,
  client_id            uuid not null references public.clients(id) on delete cascade,
  stage                public.campaign_stage not null default '0 - Backlog',
  stage_changed_at     timestamptz,
  stage_changed_by_id  uuid references public.team(id) on delete set null,
  channel              public.campaign_channel not null default 'Email',
  assignee_id          uuid references public.team(id) on delete set null,
  reviewer_id          uuid references public.team(id) on delete set null,
  sending_tool         text,
  angle                text,
  offer                text,
  list_url             text,
  list_size            int,
  copy_doc_url         text,
  due_date             date,
  launch_date          date,
  end_date             date,
  feedback_notes       text,
  notes                text,
  is_example           boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
comment on table public.campaigns is 'One campaign for one client. The "Campaigns" board.';
comment on column public.campaigns.sending_tool is 'The tool the campaign sends from, as a value (not a column per tool).';
create index campaigns_client_idx on public.campaigns (client_id);
create index campaigns_assignee_idx on public.campaigns (assignee_id);

-- Inbox batches (no board) ----------------------------------------------------
create type public.inbox_batch_stage as enum (
  '0 - Backlog',
  '10 - Approval Needed',
  '20 - Buying Domains',
  '30 - Setting Up Inboxes',
  '40 - Warming',
  '100 - Ready To Send'
);

create table public.inbox_batches (
  id                   uuid primary key default gen_random_uuid(),
  batch_name           text not null,
  client_id            uuid not null references public.clients(id) on delete cascade,
  stage                public.inbox_batch_stage not null default '0 - Backlog',
  stage_changed_at     timestamptz,
  stage_changed_by_id  uuid references public.team(id) on delete set null,
  assignee_id          uuid references public.team(id) on delete set null,
  domain_count         int not null default 0,
  inbox_count          int not null default 0,
  inbox_provider       text,
  domain_registrar     text,
  warmup_started_on    date,
  ready_on             date,
  due_date             date,
  notes                text,
  is_example           boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
comment on table public.inbox_batches is 'One batch of domains and inboxes bought for a client. No board: a list on the client page.';
create index inbox_batches_client_idx on public.inbox_batches (client_id);

create trigger campaigns_touch_updated_at before update on public.campaigns
  for each row execute function public.touch_updated_at();
create trigger inbox_batches_touch_updated_at before update on public.inbox_batches
  for each row execute function public.touch_updated_at();
select public.attach_stage_log('campaigns');
select public.attach_stage_log('inbox_batches');

-- Every open card on every board, in one shape. The dashboard reads this.
create view public.v_open_cards with (security_invoker = true) as
select 'tasks'::text as board, 'Tasks'::text as board_label, id as card_id, task_name as card_name,
       client_id, stage::text as stage, split_part(stage::text, ' ', 1)::int as stage_number,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at) as stage_changed_at, is_example
from public.tasks where stage not in ('100 - Complete', '-1 - Rejected')
union all
select 'campaigns', 'Campaigns', id, campaign_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at), is_example
from public.campaigns where stage not in ('50 - Live', '100 - Ended')
union all
select 'inbox_batches', 'Inbox batches', id, batch_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, null::uuid, due_date, coalesce(stage_changed_at, created_at), is_example
from public.inbox_batches where stage <> '100 - Ready To Send';
comment on view public.v_open_cards is 'Every open card on every board, in one shape. Live and finished cards are left out.';
