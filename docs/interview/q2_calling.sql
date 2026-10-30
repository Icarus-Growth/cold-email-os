-- Interview question: "Do you also do cold calling, or set up SDRs for clients?"
-- YES: campaigns can be calling campaigns, clients get an SDR, and the report
--      numbers get call counts.
-- NO:  skip this file.

alter type public.campaign_channel add value if not exists 'Calling';

alter table public.clients
  add column sdr_id         uuid references public.team(id) on delete set null,
  add column call_script_url text;
alter table public.daily_metrics
  add column dials           int not null default 0,
  add column connects        int not null default 0,
  add column calls_booked_by_phone int not null default 0;
alter table public.weekly_metrics
  add column dials           int not null default 0,
  add column connects        int not null default 0,
  add column calls_booked_by_phone int not null default 0;
