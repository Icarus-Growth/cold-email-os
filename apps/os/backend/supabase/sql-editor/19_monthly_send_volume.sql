-- SQL editor paste 19 of 21: 0020_monthly_send_volume.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0020  Cold email: how many emails a month the client wants to send
--
--   * clients.monthly_send_volume: the number of cold emails a month. The
--     sending set-up (domains, inboxes) is planned from it.
--   * The onboarding form asks for it (question "monthly_send_volume"). When a
--     form is filed, the database copies the answer onto the client, so it
--     lands on the client record with no extra step.
--     It fills an empty value only: a number the team typed in is kept.
--     "Not sure yet" (or any answer that is not a whole number) leaves it empty.
-- Safe to run twice.
-- =============================================================================

alter table public.clients add column if not exists monthly_send_volume int;
alter table public.clients drop constraint if exists clients_monthly_send_volume_check;
alter table public.clients add constraint clients_monthly_send_volume_check
  check (monthly_send_volume is null or monthly_send_volume >= 0);
comment on column public.clients.monthly_send_volume is
  'How many cold emails a month the client wants to send. From the onboarding form; the team can change it.';

create or replace function public.form_send_volume_to_client() returns trigger
language plpgsql set search_path = public as $fn$
declare
  v text := btrim(coalesce(new.answers -> 'monthly_send_volume' ->> 'value', ''));
begin
  if new.client_id is not null and v ~ '^[0-9]{1,9}$' then
    update public.clients set monthly_send_volume = v::int
    where id = new.client_id and monthly_send_volume is null;
  end if;
  return null;
end
$fn$;
comment on function public.form_send_volume_to_client() is
  'Copies the onboarding form''s monthly_send_volume answer onto the client, if the client has none yet (0020).';

drop trigger if exists onboarding_forms_send_volume on public.onboarding_forms;
create trigger onboarding_forms_send_volume after insert on public.onboarding_forms
  for each row execute function public.form_send_volume_to_client();
