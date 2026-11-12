-- SQL editor paste 18 of 21: 0019_live_cards_not_stuck.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0019  Live cards are not stuck and not late
--
-- 0018 (made per agency type) keeps live and waiting cards open, and marks
-- them with v_open_cards.is_live. Nobody has to act on them today. So:
--   * v_stuck_cards and v_late_cards leave them out;
--   * v_team_load counts them as open cards, but not as late cards;
--   * v_clients_attention does not count them as stuck or late.
-- They still show on My Work, on their board, and in the open card counts.
-- Safe to run twice.
-- =============================================================================

-- These two take the new is_live column (through c.*), so they are made again.
drop view if exists public.v_stuck_cards;
create view public.v_stuck_cards with (security_invoker = true) as
select c.*,
       floor(extract(epoch from now() - c.stage_changed_at) / 86400)::int as days_in_stage
from public.v_open_cards c
cross join public.settings s
where not c.is_live
  and c.stage_changed_at < now() - make_interval(days => s.stuck_after_days);
comment on view public.v_stuck_cards is 'Open cards that have not moved for settings.stuck_after_days days. Live cards are left out.';

drop view if exists public.v_late_cards;
create view public.v_late_cards with (security_invoker = true) as
select c.*, (current_date - c.due_date) as days_late
from public.v_open_cards c
where not c.is_live
  and c.due_date < current_date;
comment on view public.v_late_cards is 'Open cards past their due date. Live cards are left out.';

create or replace view public.v_team_load with (security_invoker = true) as
select t.id as team_id,
       t.full_name,
       t.capacity,
       count(c.card_id)::int as open_cards,
       count(c.card_id) filter (where c.due_date < current_date and not c.is_live)::int as late_cards,
       count(c.card_id) filter (where c.stage_number % 10 = 9)::int as sent_back_cards,
       count(c.card_id) > t.capacity as overloaded
from public.team t
left join public.v_open_cards c on c.assignee_id = t.id
where t.status = 'Active'
group by t.id, t.full_name, t.capacity;
comment on view public.v_team_load is 'Open cards per person (live cards too) against how many they can hold. Live cards are never late.';

create or replace view public.v_clients_attention with (security_invoker = true) as
with s as (select * from public.settings limit 1),
counts as (
  select c.client_id,
         count(*) filter (where not c.is_live
                          and c.stage_changed_at < now() - make_interval(days => (select stuck_after_days from s)))::int as stuck_cards,
         count(*) filter (where not c.is_live and c.due_date < current_date)::int as late_cards,
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
where cl.status = 'Active' and cl.archived_at is null;
comment on view public.v_clients_attention is 'Active clients (not archived) with stuck or late cards (live cards do not count), or onboarding that has not moved.';
