/* Copy documents (migration 0013): one row per piece of copy, on a card or on the client page.
 * The database makes a document on first open (open_document) and refuses a save over a version
 * that is not the newest (save_document raises document_conflict). It keeps the last 20 saves.
 *
 * A document is named by its client, its board and card (null on the client page) and its field
 * key: the link column's name without "_url" (copy_doc, script, caption...). */
import * as DB from './db';
import type { Row } from './db';
import { ensureQuery, useQuery, type Query, type QuerySpec } from './store';

/** The biggest body the database takes (0013: 500 000 bytes). */
export const MAX_BYTES = 500000;

export interface DocKey { client: string; board: string | null; card: string | null; field: string }

const one = (r: unknown): Row | null => (Array.isArray(r) ? (r[0] as Row) || null : (r as Row) || null);

/** The document (made on first open). */
export async function openDocument(k: DocKey): Promise<Row> {
  const r = one(await DB.rpc('open_document', { p_client: k.client, p_board: k.board, p_card: k.card, p_field: k.field }));
  if (!r || !r.id) throw new Error('open_document returned no document');
  return r;
}

/** Save a new version over `version`; resolves with the new version number. */
export async function saveDocument(id: string, version: number, body: string, words: number): Promise<{ version: number }> {
  if (new TextEncoder().encode(body).length > MAX_BYTES) throw new Error('This copy is longer than the 500 000 bytes a document can hold. Split it into two documents.');
  const r = await DB.rpc('save_document', { p_id: id, p_version: version, p_body_md: body, p_word_count: words });
  const v = typeof r === 'number' ? r : Number((one(r) || {} as Row).version ?? (one(r) || {} as Row).save_document);
  return { version: isNaN(v) ? version + 1 : v };
}

/** The saves of a document, newest first (the database keeps 20). */
export async function versions(id: string): Promise<Row[]> {
  return (await DB.select('document_versions', { filter: 'document_id=eq.' + encodeURIComponent(id), order: 'version.desc', limit: 20 })).rows;
}

/** The query for the documents of one card, or of one client's page. */
export function docsSpec(client: string, board: string | null, card: string | null): QuerySpec {
  const e = encodeURIComponent;
  return {
    key: 'docs:' + client + ':' + (board || '-') + ':' + (card || '-'), table: 'documents', ttl: 30000, acceptsInserts: false,
    opts: { select: 'id,field_key,word_count,version,updated_by,updated_at',
      filter: board && card ? 'board=eq.' + e(board) + '&card_id=eq.' + e(card) : 'client_id=eq.' + e(client) + '&board=is.null&card_id=is.null' },
  };
}
/** The documents of one card or client page (word counts and who saved last). */
export function useDocs(client: string, board: string | null, card: string | null): Query {
  return useQuery(docsSpec(client, board, card));
}
/** Read them again (after the editor closes). */
export function refreshDocs(client: string, board: string | null, card: string | null): void {
  ensureQuery(docsSpec(client, board, card), true);
}
