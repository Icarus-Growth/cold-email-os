-- =============================================================================
-- 0018  Only a "100 - ..." stage is finished. Live stages stay open.
--
-- Before: some boards left a live or waiting stage out of the open cards view
-- (campaigns at '50 - Live'). Those cards dropped off My Work and the
-- dashboard while the work was still running.
-- Now:
--   * A card is finished only at a stage numbered 100 (or -1, rejected). Every
--     other card is open, so it shows on My Work and on its board.
--   * is_live (new, last column): true for a live or waiting stage (campaigns:
--     '50 - Live'). Nobody has to act on these cards today, so the stuck and
--     late lists leave them out (0019). Nothing else does. A new board added
--     to this view needs the same conditions and an is_live column. Safe to
--     run twice.
-- =============================================================================

create or replace view public.v_open_cards with (security_invoker = true) as
select 'tasks'::text as board, 'Tasks'::text as board_label, id as card_id, task_name as card_name,
       client_id, stage::text as stage, split_part(stage::text, ' ', 1)::int as stage_number,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at) as stage_changed_at, is_example,
       false as is_live
from public.tasks x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'campaigns', 'Campaigns', id, campaign_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, reviewer_id, due_date, coalesce(stage_changed_at, created_at), is_example,
       x.stage in ('50 - Live')
from public.campaigns x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null)
union all
select 'inbox_batches', 'Inbox set-ups', id, batch_name,
       client_id, stage::text, split_part(stage::text, ' ', 1)::int,
       assignee_id, null::uuid, due_date, coalesce(stage_changed_at, created_at), is_example,
       false
from public.inbox_batches x where split_part(x.stage::text, ' ', 1)::int between 0 and 99
  and x.archived_at is null
  and not exists (select 1 from public.clients cl where cl.id = x.client_id and cl.archived_at is not null);
comment on view public.v_open_cards is 'Every open card on every board, in one shape. Finished (100), rejected (-1) and archived cards, and the cards of archived clients, are left out. is_live: a live or waiting stage, left out of the stuck and late lists.';
comment on column public.v_open_cards.is_live is 'True for a live or waiting stage (nobody must act today). The stuck and late lists leave these cards out.';
