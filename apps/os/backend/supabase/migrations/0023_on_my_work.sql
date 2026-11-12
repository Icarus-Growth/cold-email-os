-- =============================================================================
-- 0023  The open cards view says which cards belong on My Work
--
-- on_my_work (new, last column of v_open_cards): false for a card that stays
-- open but that nobody works on day to day.
-- In this agency type every open card is on My Work, so it is always true.
-- Every other open card is on My Work. The AI connector's "my queue" reads it.
-- The same view as in 0018 otherwise. Safe to run twice.
-- =============================================================================

create or replace view public.v_open_cards with (security_invoker = true) as
select 'tasks'::text as board, 'Tasks'::text as board_label, id as card_id, task_name as card_name,
       client_id, stage::text as stage, split_part(stage::text, ' ', 1)::int as stage_number,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at) as stage_changed_at, is_example,
       false as is_live,
       true as on_my_work
from public.tasks x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'campaigns', 'Campaigns', id, campaign_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at), is_example,
       x.stage in ('50 - Live'),
       true
from public.campaigns x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'inbox_batches', 'Inbox set-ups', id, batch_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, null::uuid, due_date, coalesce(stage_changed_at, created_at), is_example,
       false,
       true
from public.inbox_batches x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null);
comment on column public.v_open_cards.on_my_work is 'False for an open card that is not on My Work (a live email flow). True for every other open card.';
