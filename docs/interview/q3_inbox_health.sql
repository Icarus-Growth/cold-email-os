-- Interview question: "Do you check inbox health (spam placement, blocklists)?"
-- YES: adds health columns to each inbox batch.
-- NO:  skip this file.

alter table public.inbox_batches
  add column last_health_check_at timestamptz,
  add column healthy              boolean,
  add column blocklisted          boolean not null default false,
  add column spam_placement_rate  numeric,
  add column health_notes         text;
comment on column public.inbox_batches.spam_placement_rate is 'Share of test emails that landed in spam, from 0 to 1.';
