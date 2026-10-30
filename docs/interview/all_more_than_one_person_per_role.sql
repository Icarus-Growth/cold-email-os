-- Interview question (all agency types):
--   "Does a client ever get more than one person in the same role?"
-- YES: adds client_team, so a client can have many people per role.
--      The role columns on clients stay as "the lead person" for that role.
-- NO:  skip this file.

create table public.client_team (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references public.clients(id) on delete cascade,
  team_id     uuid not null references public.team(id) on delete cascade,
  role        text not null,
  is_lead     boolean not null default false,
  is_example  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (client_id, team_id, role)
);
comment on table public.client_team is 'One person in one role on one client. Used when a client has more than one person per role.';
create trigger client_team_touch_updated_at before update on public.client_team
  for each row execute function public.touch_updated_at();
select public.lock_table('client_team');
