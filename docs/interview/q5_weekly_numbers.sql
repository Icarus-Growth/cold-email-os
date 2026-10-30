-- Interview question: "Which numbers do you report every week?"
-- The basic numbers are already there: emails sent, replies, positive replies,
-- meetings booked, bounce rate. For each EXTRA number the agency owner names,
-- keep its two lines below and delete the rest. If none, skip this file.

alter table public.daily_metrics  add column if not exists leads_contacted int not null default 0;
alter table public.weekly_metrics add column if not exists leads_contacted int not null default 0;

alter table public.daily_metrics  add column if not exists opportunities int not null default 0;
alter table public.weekly_metrics add column if not exists opportunities int not null default 0;

alter table public.daily_metrics  add column if not exists pipeline_value numeric(14,2) not null default 0;
alter table public.weekly_metrics add column if not exists pipeline_value numeric(14,2) not null default 0;

alter table public.daily_metrics  add column if not exists unsubscribes int not null default 0;
alter table public.weekly_metrics add column if not exists unsubscribes int not null default 0;
