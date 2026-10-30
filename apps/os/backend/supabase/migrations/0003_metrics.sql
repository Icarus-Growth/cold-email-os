-- =============================================================================
-- 0003  Report numbers: cold email
--
-- daily_metrics:  one client on one day.
-- weekly_metrics: one client in one week (week_start is a Monday).
-- They stay empty until you connect your sending tool. The tool is a value in
-- the "source" column, never a column name.
-- Rates are worked out by the database from the counts, so they never drift.
-- =============================================================================

create table public.daily_metrics (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references public.clients(id) on delete cascade,
  metric_date       date not null,
  emails_sent       int not null default 0,
  replies           int not null default 0,
  positive_replies  int not null default 0,
  meetings_booked   int not null default 0,
  bounces           int not null default 0,
  bounce_rate       numeric generated always as (round(bounces::numeric / nullif(emails_sent, 0), 4)) stored,
  reply_rate        numeric generated always as (round(replies::numeric / nullif(emails_sent, 0), 4)) stored,
  source            text,
  is_example        boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (client_id, metric_date)
);
comment on table public.daily_metrics is 'One client on one day. Cold email numbers.';

create table public.weekly_metrics (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references public.clients(id) on delete cascade,
  week_start        date not null,
  emails_sent       int not null default 0,
  replies           int not null default 0,
  positive_replies  int not null default 0,
  meetings_booked   int not null default 0,
  bounces           int not null default 0,
  bounce_rate       numeric generated always as (round(bounces::numeric / nullif(emails_sent, 0), 4)) stored,
  reply_rate        numeric generated always as (round(replies::numeric / nullif(emails_sent, 0), 4)) stored,
  note              text,
  is_example        boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (client_id, week_start)
);
comment on table public.weekly_metrics is 'One client in one week. The daily numbers summed, plus a short note.';

create trigger daily_metrics_touch_updated_at before update on public.daily_metrics
  for each row execute function public.touch_updated_at();
create trigger weekly_metrics_touch_updated_at before update on public.weekly_metrics
  for each row execute function public.touch_updated_at();
