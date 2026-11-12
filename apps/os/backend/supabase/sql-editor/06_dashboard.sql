-- SQL editor paste 6 of 19: 0006_dashboard.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0006  The saved views the dashboard reads
--
-- The dashboard answers three questions:
--   1. What is stuck or late?          v_stuck_cards, v_late_cards
--   2. Who is overloaded?              v_team_load
--   3. Which clients need attention?   v_clients_attention
--
-- They all read v_open_cards (made in 0004, because the boards differ per
-- agency type). Every view reads with the rights of the person asking
-- (security_invoker), so a person who is not on the team sees nothing.
-- =============================================================================

create view public.v_stuck_cards with (security_invoker = true) as
select c.*,
       floor(extract(epoch from now() - c.stage_changed_at) / 86400)::int as days_in_stage
from public.v_open_cards c
cross join public.settings s
where c.stage_changed_at < now() - make_interval(days => s.stuck_after_days);
comment on view public.v_stuck_cards is 'Open cards that have not moved for settings.stuck_after_days days.';

create view public.v_late_cards with (security_invoker = true) as
select c.*, (current_date - c.due_date) as days_late
from public.v_open_cards c
where c.due_date < current_date;
comment on view public.v_late_cards is 'Open cards past their due date.';

create view public.v_team_load with (security_invoker = true) as
select t.id as team_id,
       t.full_name,
       t.capacity,
       count(c.card_id)::int as open_cards,
       count(c.card_id) filter (where c.due_date < current_date)::int as late_cards,
       count(c.card_id) filter (where c.stage_number % 10 = 9)::int as sent_back_cards,
       count(c.card_id) > t.capacity as overloaded
from public.team t
left join public.v_open_cards c on c.assignee_id = t.id
where t.status = 'Active'
group by t.id, t.full_name, t.capacity;
comment on view public.v_team_load is 'Open cards per person against how many they can hold.';

create view public.v_clients_attention with (security_invoker = true) as
with s as (select * from public.settings limit 1),
counts as (
  select c.client_id,
         count(*) filter (where c.stage_changed_at < now() - make_interval(days => (select stuck_after_days from s)))::int as stuck_cards,
         count(*) filter (where c.due_date < current_date)::int as late_cards,
         count(*) filter (where c.stage_number % 10 = 9)::int as sent_back_cards
  from public.v_open_cards c
  where c.client_id is not null
  group by c.client_id
)
select cl.id as client_id,
       cl.client_name,
       cl.account_manager_id,
       cl.onboarding_stage,
       coalesce(k.stuck_cards, 0) as stuck_cards,
       coalesce(k.late_cards, 0) as late_cards,
       coalesce(k.sent_back_cards, 0) as sent_back_cards,
       (cl.onboarding_stage <> '100 - Onboarded'
        and coalesce(cl.onboarding_stage_changed_at, cl.created_at)
            < now() - make_interval(days => (select onboarding_stuck_after_days from s))) as onboarding_stuck,
       (coalesce(k.stuck_cards, 0) + coalesce(k.late_cards, 0) > 0
        or (cl.onboarding_stage <> '100 - Onboarded'
            and coalesce(cl.onboarding_stage_changed_at, cl.created_at)
                < now() - make_interval(days => (select onboarding_stuck_after_days from s)))) as needs_attention
from public.clients cl
left join counts k on k.client_id = cl.id
where cl.status = 'Active';
comment on view public.v_clients_attention is 'Active clients with stuck or late cards, or onboarding that has not moved.';
