-- SQL editor paste 16 of 19: 0017_inbox_set_ups_board.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0017  Cold email: inbox batches become the "Inbox set-ups" board
--
-- Boards on the Tasks screen are now: Tasks, Campaigns and Inbox set-ups.
-- The table keeps its name (inbox_batches) and its stage list
-- (inbox_batch_stage). It already had a stage log (0004) and archive (0010).
--
--   * position: the order of a card inside its stage, as on a board.
--   * The open cards view names the board "Inbox set-ups".
-- Safe to run twice.
-- =============================================================================

alter table public.inbox_batches add column if not exists position int not null default 1;
comment on column public.inbox_batches.position is 'The order of the card inside its stage. Lower comes first.';
comment on table public.inbox_batches is 'One batch of domains and inboxes bought and warmed for a client. The "Inbox set-ups" board.';

-- The open cards view as in 0011, with the board's new name.
create or replace view public.v_open_cards with (security_invoker = true) as
select 'tasks'::text as board, 'Tasks'::text as board_label, id as card_id, task_name as card_name,
       client_id, stage::text as stage, split_part(stage::text, ' ', 1)::int as stage_number,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at) as stage_changed_at, is_example
from public.tasks x where (stage not in ('100 - Complete', '-1 - Rejected'))
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'campaigns', 'Campaigns', id, campaign_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at), is_example
from public.campaigns x where (stage not in ('50 - Live', '100 - Ended'))
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'inbox_batches', 'Inbox set-ups', id, batch_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, null::uuid, due_date, coalesce(stage_changed_at, created_at), is_example
from public.inbox_batches x where (stage <> '100 - Ready To Send')
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null);
comment on view public.v_open_cards is 'Every open card on every board, in one shape. Finished and archived cards, and the cards of archived clients, are left out.';
