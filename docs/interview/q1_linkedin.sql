-- Interview question: "Do you also sell LinkedIn outreach?"
-- YES: campaigns can be LinkedIn campaigns, and the report numbers get LinkedIn counts.
-- NO:  skip this file.

alter type public.campaign_channel add value if not exists 'LinkedIn';

alter table public.clients add column linkedin_profile_url text;
alter table public.daily_metrics
  add column connection_requests_sent int not null default 0,
  add column connections_accepted     int not null default 0,
  add column linkedin_replies         int not null default 0;
alter table public.weekly_metrics
  add column connection_requests_sent int not null default 0,
  add column connections_accepted     int not null default 0,
  add column linkedin_replies         int not null default 0;
