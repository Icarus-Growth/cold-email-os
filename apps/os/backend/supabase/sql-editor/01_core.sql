-- SQL editor paste 1 of 21: 0001_core.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0001  The core tables: team, clients, tasks, calls, onboarding forms, settings
--
-- Rules every change file follows:
--   * The wide-table rule. A new field goes on the parent table as a column.
--     A new table needs proof that one parent has MANY of the thing.
--   * Stages are numbered labels ("0 - Backlog", "29 - Amendments",
--     "100 - Complete"). They are stored as a Postgres enum, so they sort in
--     ladder order and show as a dropdown in the Supabase table editor.
--     A number ending in 9 means the work is held (sent back or blocked).
--   * Column names never name a tool. The tool is a value in a column.
--   * Keys, tokens and passwords are NEVER stored in a table.
--   * Every main table has is_example. Example rows are deleted with
--     docs/examples/delete_examples.sql.
-- =============================================================================

-- Keeps updated_at current on every table that has it.
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $fn$
begin
  new.updated_at := now();
  return new;
end
$fn$;

-- -----------------------------------------------------------------------------
-- Ladders and lists
-- -----------------------------------------------------------------------------
create type public.team_access as enum ('Owner', 'Admin', 'Member');
create type public.team_status as enum ('Active', 'Inactive');
create type public.client_status as enum ('Active', 'Paused', 'Ended');
create type public.onboarding_stage as enum (
  '0 - Paid',
  '10 - Contract Sent',
  '20 - Contract Signed',
  '30 - Set-Up',
  '40 - Call Booked',
  '50 - Call Taken',
  '100 - Onboarded'
);
create type public.task_stage as enum (
  '-1 - Rejected',
  '0 - Backlog',
  '9 - Blocked',
  '10 - In Progress',
  '29 - Amendments',
  '30 - In Review',
  '100 - Complete'
);
create type public.call_type as enum ('Sales', 'Onboarding', 'Check-In', 'Internal', 'Other');

-- -----------------------------------------------------------------------------
-- settings: one row. The numbers the dashboard and the daily summary use.
-- -----------------------------------------------------------------------------
create table public.settings (
  id                         int primary key default 1 check (id = 1),
  agency_name                text,
  time_zone                  text not null default 'Europe/London',
  stuck_after_days           int  not null default 3,
  onboarding_stuck_after_days int not null default 7,
  daily_summary_hour         int  not null default 8 check (daily_summary_hour between 0 and 23),
  os_url                     text,
  onboarding_url             text,
  updated_at                 timestamptz not null default now()
);
insert into public.settings (id) values (1);
comment on table public.settings is 'One row. The numbers the dashboard and the daily summary use.';
comment on column public.settings.stuck_after_days is 'A card that has not moved for this many days counts as stuck.';

-- -----------------------------------------------------------------------------
-- team: one person in the agency. "can_sign_in" is the allow-list.
-- -----------------------------------------------------------------------------
create table public.team (
  id             uuid primary key default gen_random_uuid(),
  full_name      text not null,
  email          text not null unique check (email = lower(email)),
  job_title      text,
  access         public.team_access not null default 'Member',
  status         public.team_status not null default 'Active',
  can_sign_in    boolean not null default false,
  capacity       int not null default 10,
  slack_user_id  text,
  phone          text,
  notes          text,
  is_example     boolean not null default false,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
comment on table public.team is 'One person in the agency.';
comment on column public.team.can_sign_in is 'The allow-list. Only Active people with this ticked can see any data.';
comment on column public.team.access is 'Owner and Admin can add people and give access. Member cannot.';
comment on column public.team.capacity is 'How many open cards this person can hold before the dashboard shows them as overloaded.';

-- -----------------------------------------------------------------------------
-- clients: one client of the agency. Wide on purpose.
-- The agency-type columns and the other role columns are added in 0004.
-- -----------------------------------------------------------------------------
create table public.clients (
  id                          uuid primary key default gen_random_uuid(),
  client_name                 text not null,
  status                      public.client_status not null default 'Active',
  website                     text,
  contact_name                text,
  contact_email               text,
  contact_phone               text,
  start_date                  date,
  end_date                    date,
  services                    text[] not null default '{}',
  onboarding_stage            public.onboarding_stage not null default '0 - Paid',
  onboarding_stage_changed_at timestamptz,
  onboarding_stage_changed_by_id uuid references public.team(id) on delete set null,
  account_manager_id          uuid references public.team(id) on delete set null,
  slack_channel_id            text,
  slack_channel_name          text,
  drive_folder_url            text,
  form_code                   text not null unique default replace(gen_random_uuid()::text, '-', ''),
  form_received_at            timestamptz,
  notes                       text,
  is_example                  boolean not null default false,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now()
);
comment on table public.clients is 'One client of the agency. Wide on purpose: a new field is a new column here.';
comment on column public.clients.form_code is 'The random code in the client''s onboarding form link. It cannot be guessed.';
comment on column public.clients.slack_channel_id is 'The client''s own Slack channel. Automations only pin one welcome message there.';

-- -----------------------------------------------------------------------------
-- tasks: one ad-hoc task, for anyone. The "Tasks" board.
-- -----------------------------------------------------------------------------
create table public.tasks (
  id                   uuid primary key default gen_random_uuid(),
  task_name            text not null,
  client_id            uuid references public.clients(id) on delete cascade,
  stage                public.task_stage not null default '0 - Backlog',
  stage_changed_at     timestamptz,
  stage_changed_by_id  uuid references public.team(id) on delete set null,
  assignee_id          uuid references public.team(id) on delete set null,
  reviewer_id          uuid references public.team(id) on delete set null,
  due_date             date,
  links                text,
  notes                text,
  created_by_id        uuid references public.team(id) on delete set null,
  is_example           boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
comment on table public.tasks is 'One ad-hoc task. The "Tasks" board.';

-- -----------------------------------------------------------------------------
-- calls: one call (sales, onboarding, check-in).
-- -----------------------------------------------------------------------------
create table public.calls (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid references public.clients(id) on delete cascade,
  title           text not null,
  call_type       public.call_type not null default 'Check-In',
  call_at         timestamptz not null default now(),
  recording_url   text,
  summary         text,
  transcript      text,
  action_items    text,
  attendees       text,
  is_example      boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
comment on table public.calls is 'One call with a client or about a client.';

-- -----------------------------------------------------------------------------
-- onboarding_forms: one submitted onboarding form.
-- onboarding_form_drafts: the half-filled form behind a shared link. Only the
-- form app's server reads or writes it (with the secret key), so two people at
-- the client can fill the same link. No one else gets a policy on it.
-- -----------------------------------------------------------------------------
create table public.onboarding_forms (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid references public.clients(id) on delete set null,
  form_key            text not null default 'onboarding',
  submitted_by_name   text,
  submitted_by_email  text,
  company_name        text,
  answers             jsonb not null default '{}'::jsonb,
  submitted_at        timestamptz not null default now(),
  is_example          boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.onboarding_forms is 'One submitted onboarding form. Answers are one block, keyed by question.';

create table public.onboarding_form_drafts (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid references public.clients(id) on delete cascade,
  form_key        text not null default 'onboarding',
  answers         jsonb not null default '{}'::jsonb,
  current_step    int not null default 1,
  last_editor_email text,
  submission_id   uuid references public.onboarding_forms(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (client_id, form_key)
);
comment on table public.onboarding_form_drafts is 'A half-filled form. Server only: no one else can read it.';

-- updated_at on every table above
do $t$
declare t text;
begin
  foreach t in array array['settings','team','clients','tasks','calls','onboarding_forms','onboarding_form_drafts'] loop
    execute format('create trigger %I before update on public.%I for each row execute function public.touch_updated_at()',
                   t || '_touch_updated_at', t);
  end loop;
end
$t$;

create index tasks_assignee_idx on public.tasks (assignee_id);
create index tasks_client_idx on public.tasks (client_id);
create index calls_client_idx on public.calls (client_id, call_at desc);
create index onboarding_forms_client_idx on public.onboarding_forms (client_id);
