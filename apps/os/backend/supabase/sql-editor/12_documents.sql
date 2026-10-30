-- SQL editor paste 12 of 15: 0013_documents.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0013  Copy documents
--
-- A document is the text of one field: a card's script, brief or copy, or a
-- client page's offer or research doc. The app's editor opens it and saves it.
-- Markdown is the stored form.
--
--   * documents: one row per (client, board, card, field). board is the card's
--     table name; board and card_id are empty for a client-page document.
--   * document_versions: the text before each save. The last 20 per document.
--   * document_fields: which fields are documents (filled per agency type, in
--     0014). open_document refuses any other field.
--   * open_document(client, board, card, field): the row; made on first open.
--   * save_document(id, version, body_md, word_count[, saved_by]): saves and
--     returns the new version. Raises document_conflict when the version is not
--     the current one (someone else saved first).
--
-- Who saved: a signed-in person is always recorded as themselves. saved_by is
-- used only by the server (the AI connector, which has no sign-in).
-- Access: every team member reads every document, the same as cards and
-- clients. Text changes go only through save_document. Only an Owner or Admin
-- archives (0010); archive_client and restore_client include documents.
-- No automation call and no Slack message on a save.
-- =============================================================================

create table if not exists public.document_fields (
  board        text,
  field_key    text not null,
  label        text not null,
  link_column  text,
  constraint document_fields_key unique nulls not distinct (board, field_key)
);
comment on table public.document_fields is
  'Which fields are documents. board = the card table; empty = the client page. link_column = the "paste a link instead" column.';

create table if not exists public.documents (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references public.clients(id) on delete cascade,
  board       text,
  card_id     uuid,
  field_key   text not null,
  body_md     text not null default '',
  word_count  integer not null default 0,
  version     integer not null default 1,
  updated_by  uuid references public.team(id) on delete set null,
  updated_at  timestamptz not null default now(),
  created_at  timestamptz not null default now(),
  archived_at timestamptz,
  constraint documents_key unique nulls not distinct (client_id, board, card_id, field_key),
  constraint documents_body_size check (octet_length(body_md) <= 500000),
  constraint documents_word_count check (word_count >= 0),
  constraint documents_client_page check (board is not null or card_id is null)
);
comment on table public.documents is
  'The text of one document field, as Markdown. board and card_id are empty for a client-page document. Saved through save_document().';
create index if not exists documents_card_idx on public.documents (board, card_id);

create table if not exists public.document_versions (
  document_id uuid not null references public.documents(id) on delete cascade,
  version     integer not null,
  body_md     text not null,
  word_count  integer not null,
  saved_by    uuid references public.team(id) on delete set null,
  saved_at    timestamptz not null,
  primary key (document_id, version)
);
comment on table public.document_versions is
  'The text of a document before each save (who saved that text, and when). The last 20 per document. Written by the database only.';

-- Each save keeps the text it replaces, then trims the history to 20. An empty
-- text (a document never written) is not kept.
create or replace function public.keep_document_version() returns trigger
language plpgsql security definer set search_path = public as $fn$
begin
  if old.body_md <> '' then
    insert into public.document_versions (document_id, version, body_md, word_count, saved_by, saved_at)
    values (old.id, old.version, old.body_md, old.word_count, old.updated_by, old.updated_at)
    on conflict (document_id, version) do nothing;
    delete from public.document_versions
    where document_id = old.id
      and version not in (select version from public.document_versions
                          where document_id = old.id order by version desc limit 20);
  end if;
  return null;
end
$fn$;

drop trigger if exists documents_keep_version on public.documents;
create trigger documents_keep_version after update of body_md on public.documents
  for each row when (old.body_md is distinct from new.body_md)
  execute function public.keep_document_version();

-- Who is calling: a signed-in team member (returns their team id), or the
-- server with the secret key or the SQL editor (returns null). Anyone else is
-- refused.
create or replace function public.document_caller() returns uuid
language plpgsql stable security definer set search_path = public as $fn$
begin
  if coalesce(auth.jwt() ->> 'email', '') <> '' then
    if not public.is_team() then
      raise exception 'Only the team can open or save documents.' using errcode = '42501';
    end if;
    return public.current_team_id();
  end if;
  if coalesce(auth.jwt() ->> 'role', '') in ('anon', 'authenticated') then
    raise exception 'Only the team can open or save documents.' using errcode = '42501';
  end if;
  return null;
end
$fn$;

create or replace function public.open_document(p_client uuid, p_board text, p_card uuid, p_field text)
returns public.documents
language plpgsql security definer set search_path = public as $fn$
declare
  card_ok boolean;
  doc     public.documents;
begin
  perform public.document_caller();
  if not exists (select 1 from public.document_fields
                 where board is not distinct from p_board and field_key = p_field) then
    raise exception 'There is no document field "%" on %.', p_field, coalesce(p_board, 'the client page')
      using errcode = '22023';
  end if;
  if p_board is null then
    if p_card is not null then
      raise exception 'A client-page document has no card.' using errcode = '22023';
    end if;
    card_ok := exists (select 1 from public.clients where id = p_client);
  else
    execute format('select exists (select 1 from public.%I where id = $1 and client_id = $2)', p_board)
      into card_ok using p_card, p_client;
  end if;
  if not card_ok then
    raise exception 'There is no such card for that client.' using errcode = 'P0002';
  end if;

  insert into public.documents (client_id, board, card_id, field_key)
  values (p_client, p_board, p_card, p_field)
  on conflict on constraint documents_key do nothing;

  select * into doc from public.documents
  where client_id = p_client and board is not distinct from p_board
    and card_id is not distinct from p_card and field_key = p_field;
  return doc;
end
$fn$;
comment on function public.open_document(uuid, text, uuid, text) is
  'The document for one field of a card (or of the client page, with board and card empty). Makes it, empty, on first open.';

create or replace function public.save_document(p_id uuid, p_version integer, p_body_md text, p_word_count integer,
                                                p_saved_by uuid default null)
returns integer
language plpgsql security definer set search_path = public as $fn$
declare
  who uuid := public.document_caller();
  doc public.documents;
begin
  if who is null then
    who := p_saved_by;  -- only the server gets here
  end if;
  if octet_length(coalesce(p_body_md, '')) > 500000 then
    raise exception 'The document is too long: % bytes. The most is 500 000 bytes. Split it, or paste a link instead.',
      octet_length(p_body_md) using errcode = '22001';
  end if;
  select * into doc from public.documents where id = p_id for update;
  if not found then
    raise exception 'There is no document with that id.' using errcode = 'P0002';
  end if;
  if doc.version is distinct from p_version then
    raise exception 'document_conflict'
      using errcode = 'P0001',
            detail = format('The document is at version %s, not %s. Someone else changed it.', doc.version, p_version),
            hint = 'Reload to see their changes.';
  end if;
  if doc.body_md = coalesce(p_body_md, '') then
    return doc.version;  -- nothing changed: no new version
  end if;
  update public.documents
  set body_md = coalesce(p_body_md, ''),
      word_count = greatest(coalesce(p_word_count, 0), 0),
      version = doc.version + 1,
      updated_by = who,
      updated_at = now()
  where id = p_id;
  return doc.version + 1;
end
$fn$;
comment on function public.save_document(uuid, integer, text, integer, uuid) is
  'Saves a document and returns the new version. Raises document_conflict when p_version is not the current one. A signed-in person is recorded as themselves; p_saved_by is for the server only.';

-- Access. Rows: team only (lock_table). Columns: people read; the only column
-- a person writes directly is archived_at (Owner or Admin, 0010). The text
-- changes only through save_document.
select public.lock_table('document_fields', true);
select public.lock_table('documents');
select public.lock_table('document_versions', true);

revoke all on public.document_fields, public.documents, public.document_versions from anon, authenticated;
grant select on public.document_fields, public.documents, public.document_versions to authenticated;
grant update (archived_at) on public.documents to authenticated;

revoke all on function public.document_caller() from public, anon;
revoke all on function public.keep_document_version() from public, anon, authenticated;
revoke all on function public.open_document(uuid, text, uuid, text) from public, anon;
revoke all on function public.save_document(uuid, integer, text, integer, uuid) from public, anon;
grant execute on function public.document_caller() to authenticated, service_role;
grant execute on function public.open_document(uuid, text, uuid, text) to authenticated, service_role;
grant execute on function public.save_document(uuid, integer, text, integer, uuid) to authenticated, service_role;
