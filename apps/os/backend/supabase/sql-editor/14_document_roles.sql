-- SQL editor paste 14 of 21: 0015_document_roles.sql
-- Paste all of this into the Supabase SQL editor and press Run.
-- Wait for "Success" before you paste the next file.

-- =============================================================================
-- 0015  Only an Owner or Admin saves a client-page document
--
-- Before: save_document (0013) checked only "on the team", so a Member could
-- change a client-page document (the offer doc, the research doc, ...).
-- Now:
--   * a client-page document (board empty) is saved only by an Owner or Admin;
--     a Member gets a plain error and nothing changes;
--   * a card document is still saved by any team member;
--   * the server (the AI connector, no sign-in) is not checked, as before.
-- open_document does not change: a Member may still open and read a
-- client-page document.
-- Safe to run twice.
-- =============================================================================

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
  -- A client-page document (no board) is part of the client record: only an
  -- Owner or Admin changes it. The server (no sign-in) is not checked.
  if doc.board is null and coalesce(auth.jwt() ->> 'email', '') <> '' and not public.is_admin() then
    raise exception 'Only an Owner or Admin can change a client-page document. You can still read it.'
      using errcode = '42501';
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
  'Saves a document and returns the new version. Raises document_conflict when p_version is not the current one. A client-page document: Owner or Admin only. A signed-in person is recorded as themselves; p_saved_by is for the server only.';
