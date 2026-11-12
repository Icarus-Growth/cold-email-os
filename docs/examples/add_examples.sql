-- =============================================================================
-- Example rows. Every row here is fake and has is_example = true.
-- Remove them all with docs/examples/delete_examples.sql.
-- Example people cannot sign in (can_sign_in = false).
-- =============================================================================

insert into public.team (id, full_name, email, job_title, access, can_sign_in, capacity, is_example) values
  ('aaaaaaaa-0000-4000-8000-000000000001', 'Alex Example',  'alex@example.com',  'Account Manager', 'Member', false, 8, true),
  ('aaaaaaaa-0000-4000-8000-000000000002', 'Sam Example',   'sam@example.com',   'Specialist',      'Member', false, 6, true),
  ('aaaaaaaa-0000-4000-8000-000000000003', 'Jordan Example','jordan@example.com','Specialist',      'Member', false, 2, true);

insert into public.clients (id, client_name, status, website, contact_name, contact_email, start_date,
                            onboarding_stage, account_manager_id, notes, is_example) values
  ('cccccccc-0000-4000-8000-000000000001', 'Example Client A', 'Active', 'https://example.com', 'Pat Example', 'pat@example.com',
   current_date - 60, '100 - Onboarded', 'aaaaaaaa-0000-4000-8000-000000000001', 'Example row.', true),
  ('cccccccc-0000-4000-8000-000000000002', 'Example Client B', 'Active', 'https://example.org', 'Lee Example', 'lee@example.org',
   current_date - 20, '50 - Call Taken', 'aaaaaaaa-0000-4000-8000-000000000001', 'Example row.', true),
  ('cccccccc-0000-4000-8000-000000000003', 'Example Client C', 'Active', 'https://example.net', 'Kim Example', 'kim@example.net',
   current_date - 2, '10 - Contract Sent', 'aaaaaaaa-0000-4000-8000-000000000002', 'Example row.', true);

-- Onboarding that has not moved for a while, so the dashboard has something to show.
update public.clients set onboarding_stage_changed_at = now() - interval '9 days'
where id = 'cccccccc-0000-4000-8000-000000000002';

insert into public.tasks (task_name, client_id, stage, assignee_id, due_date, is_example) values
  ('Example: send the welcome pack',        'cccccccc-0000-4000-8000-000000000003', '10 - In Progress', 'aaaaaaaa-0000-4000-8000-000000000001', current_date + 1, true),
  ('Example: book the onboarding call',     'cccccccc-0000-4000-8000-000000000002', '9 - Blocked',      'aaaaaaaa-0000-4000-8000-000000000001', current_date - 2, true),
  ('Example: tidy the shared drive',        null,                                   '0 - Backlog',      'aaaaaaaa-0000-4000-8000-000000000003', null,             true),
  ('Example: monthly check-in notes',       'cccccccc-0000-4000-8000-000000000001', '30 - In Review',   'aaaaaaaa-0000-4000-8000-000000000002', current_date,     true);

insert into public.calls (client_id, title, call_type, call_at, summary, action_items, is_example) values
  ('cccccccc-0000-4000-8000-000000000001', 'Example: monthly check-in', 'Check-In',   now() - interval '7 days',
   'Example summary. The client is happy with the results so far.', 'Send the next month''s plan.', true),
  ('cccccccc-0000-4000-8000-000000000002', 'Example: onboarding call',  'Onboarding', now() - interval '3 days',
   'Example summary. Access was given during the call.', 'Start the first piece of work.', true),
  ('cccccccc-0000-4000-8000-000000000003', 'Example: sales call',       'Sales',      now() - interval '10 days',
   'Example summary. The client signed up after the call.', 'Send the contract.', true);

insert into public.onboarding_forms (client_id, submitted_by_name, submitted_by_email, company_name, answers, is_example) values
  ('cccccccc-0000-4000-8000-000000000002', 'Lee Example', 'lee@example.org', 'Example Client B',
   '{"what_do_you_sell": "Example answer.", "who_do_you_sell_to": "Example answer."}'::jsonb, true);

update public.clients set form_received_at = now() - interval '4 days'
where id = 'cccccccc-0000-4000-8000-000000000002';

-- Cold email examples ---------------------------------------------------------
update public.clients set campaign_manager_id = 'aaaaaaaa-0000-4000-8000-000000000002',
       target_market = 'Example: owners of small accounting firms',
       monthly_send_volume = 20000
where is_example;

insert into public.campaigns (campaign_name, client_id, stage, assignee_id, reviewer_id, sending_tool, angle, list_size, due_date, is_example) values
  ('Example: first outreach',      'cccccccc-0000-4000-8000-000000000001', '50 - Live',            'aaaaaaaa-0000-4000-8000-000000000002', 'aaaaaaaa-0000-4000-8000-000000000001', 'Example tool', 'Example angle', 1200, current_date - 10, true),
  ('Example: case study angle',    'cccccccc-0000-4000-8000-000000000001', '20 - Copywriting',     'aaaaaaaa-0000-4000-8000-000000000002', 'aaaaaaaa-0000-4000-8000-000000000001', 'Example tool', 'Example angle', 800,  current_date + 3,  true),
  ('Example: event follow-up',     'cccccccc-0000-4000-8000-000000000002', '29 - Copy Amendments', 'aaaaaaaa-0000-4000-8000-000000000003', 'aaaaaaaa-0000-4000-8000-000000000001', 'Example tool', 'Example angle', 400,  current_date - 1,  true),
  ('Example: new market test',     'cccccccc-0000-4000-8000-000000000002', '10 - List Building',   'aaaaaaaa-0000-4000-8000-000000000003', null,                                   'Example tool', 'Example angle', null, current_date + 7,  true);

insert into public.inbox_batches (batch_name, client_id, stage, assignee_id, domain_count, inbox_count, inbox_provider, warmup_started_on, is_example) values
  ('Example: first batch',  'cccccccc-0000-4000-8000-000000000001', '100 - Ready To Send', 'aaaaaaaa-0000-4000-8000-000000000002', 5, 15, 'Example provider', current_date - 30, true),
  ('Example: second batch', 'cccccccc-0000-4000-8000-000000000002', '40 - Warming',        'aaaaaaaa-0000-4000-8000-000000000002', 3, 9,  'Example provider', current_date - 6,  true),
  ('Example: new client',   'cccccccc-0000-4000-8000-000000000003', '10 - Approval Needed','aaaaaaaa-0000-4000-8000-000000000002', 3, 9,  'Example provider', null,              true);

insert into public.daily_metrics (client_id, metric_date, emails_sent, replies, positive_replies, meetings_booked, bounces, source, is_example) values
  ('cccccccc-0000-4000-8000-000000000001', current_date - 3, 300, 9, 3, 1, 4, 'Example tool', true),
  ('cccccccc-0000-4000-8000-000000000001', current_date - 2, 300, 7, 2, 0, 3, 'Example tool', true),
  ('cccccccc-0000-4000-8000-000000000001', current_date - 1, 300, 11, 4, 2, 2, 'Example tool', true);

insert into public.weekly_metrics (client_id, week_start, emails_sent, replies, positive_replies, meetings_booked, bounces, note, is_example) values
  ('cccccccc-0000-4000-8000-000000000001', date_trunc('week', current_date)::date - 7, 1500, 41, 14, 5, 15, 'Example note.', true);

-- Example documents (0013, 0014): one on a card, one on a client page.
insert into public.documents (client_id, board, card_id, field_key, body_md, word_count, updated_by)
select c.client_id, 'campaigns', c.id, 'copy_doc', d.body, coalesce(array_length(regexp_split_to_array(btrim(d.body), '\s+'), 1), 0), 'aaaaaaaa-0000-4000-8000-000000000001'
from public.campaigns c, (values ($doc$## Email 1

Subject: a question about your month-end

Hi {{firstName}},

We helped a firm like yours close the books two days faster. Can I send you the short case study?

Thanks,
Alex$doc$)) d(body)
where c.campaign_name = 'Example: case study angle' and c.is_example;

insert into public.documents (client_id, field_key, body_md, word_count, updated_by)
select 'cccccccc-0000-4000-8000-000000000001', 'offer_doc', d.body, coalesce(array_length(regexp_split_to_array(btrim(d.body), '\s+'), 1), 0), 'aaaaaaaa-0000-4000-8000-000000000001'
from (values ($doc$# Offer

- Who it is for: owners of small accounting firms
- What they get: 10 booked calls a month
- Guarantee: no calls, no fee$doc$)) d(body);

-- Example sending set-up and lead list (0021) ----------------------------------
insert into public.sending_domains (batch_id, client_id, domain, inbox_kind, inbox_provider, registrar, name_style,
                                    planned_price_usd, paid_price_usd, inboxes_planned, status, bought_at, dns_verified_at,
                                    warmup_started_at, ready_at, is_example)
select b.id, b.client_id, d.domain, 'google', 'Example provider', 'Example registrar', 'brand + word',
       11.00, d.paid, 3, d.status, d.bought, d.dns, d.warm, d.ready, true
from public.inbox_batches b
join (values
  ('Example: first batch',  'tryexampleclienta.com', 11.00, 'ready',   now() - interval '30 days', now() - interval '29 days', now() - interval '28 days', now() - interval '14 days'),
  ('Example: first batch',  'getexampleclienta.com', 11.00, 'ready',   now() - interval '30 days', now() - interval '29 days', now() - interval '28 days', now() - interval '14 days'),
  ('Example: second batch', 'meetexampleclientb.com', 11.00, 'warming', now() - interval '7 days',  now() - interval '6 days',  now() - interval '6 days',  null)
) as d(batch, domain, paid, status, bought, dns, warm, ready) on d.batch = b.batch_name
where b.is_example;

insert into public.sending_inboxes (domain_id, batch_id, client_id, address, first_name, last_name, inbox_kind, status,
                                    warmup_tool, warmup_daily_limit, warmup_started_at, is_example)
select d.id, d.batch_id, d.client_id, i.local || '@' || d.domain, i.first, 'Example', 'google', d.status,
       'Example warm-up tool', 20, d.warmup_started_at, true
from public.sending_domains d
cross join (values ('alex', 'Alex'), ('sam', 'Sam')) as i(local, first)
where d.is_example;

insert into public.lead_searches (client_id, keyword, location, industry, status, attempts, results_count, new_count,
                                  credits_used, searched_at, is_example) values
  ('cccccccc-0000-4000-8000-000000000001', 'accountant', 'Example City', 'Accounting', 'done',  1, 2, 2, 1, now() - interval '2 days', true),
  ('cccccccc-0000-4000-8000-000000000001', 'bookkeeper', 'Example City', 'Accounting', 'to do', 0, null, null, 0, null, true);

insert into public.lead_companies (client_id, search_id, company_name, website, domain, location, category, industry,
                                   place_id, rating, review_count, source, fit_status, fit_confidence, fit_reason,
                                   fit_method, fit_checked_at, is_example)
select s.client_id, s.id, c.name, 'https://' || c.domain, c.domain, 'Example City', 'Accountant', 'Accounting',
       c.place, c.rating, c.reviews, 'map search', c.fit, c.conf, c.why, 'free check', now() - interval '1 day', true
from public.lead_searches s
join (values
  ('Example Books Ltd',   'examplebooks.com',   'example-place-1', 4.80, 52, 'fit',     90, 'Small accounting firm. Owner-led.'),
  ('Example Tax Giants',  'exampletaxgiants.com', 'example-place-2', 4.10, 900, 'not fit', 85, 'Too large: over 1,000 people.')
) as c(name, domain, place, rating, reviews, fit, conf, why) on true
where s.is_example and s.keyword = 'accountant';

insert into public.lead_contacts (client_id, company_id, full_name, first_name, last_name, title, domain, email,
                                  email_status, email_score, email_source, email_pattern, catch_all, guess_credits,
                                  guess_checked_at, final_verdict, is_example)
select c.client_id, c.id, p.full_name, p.first, p.last, p.title, c.domain, p.email || '@' || c.domain,
       p.status, p.score, 'guessed', 'first', p.catch_all, 1, now() - interval '1 day', p.verdict, true
from public.lead_companies c
join (values
  ('Robin Example', 'Robin', 'Example', 'Owner',   'robin', 'valid',     95, false, 'send'),
  ('Kai Example',   'Kai',   'Example', 'Partner', 'kai',   'catch-all', 50, true,  null)
) as p(full_name, first, last, title, email, status, score, catch_all, verdict) on true
where c.is_example and c.fit_status = 'fit';
