/* Who may change a copy document (0013, 0015): a card's document, anyone on the team; a
 * client-page document (no board), an Owner or Admin. Others read it. The database refuses the
 * save as well (error 42501, with a plain sentence); the editor shows that sentence.
 *
 * No imports: tests/documents.test.mjs runs this file in Node as it is. */

export const READ_ONLY = 'Only an Owner or Admin can change this. You can read it.';

/** True when someone with this access may change a document on this board (null = client page). */
export function canChangeDoc(access: string | null | undefined, board: string | null): boolean {
  return !!board || access === 'Owner' || access === 'Admin';
}

/** True for the database's "not allowed" refusal. */
export const isDenied = (err: unknown): boolean => /42501|HTTP 403/.test(String((err as Error)?.message || err || ''));

/** The database's own sentence in an error ("save_document: HTTP 403 {"code":"42501","message":"..."}"),
 *  or null when it has none. */
export function dbMessage(err: unknown): string | null {
  const m = String((err as Error)?.message || err || '');
  const at = m.indexOf('{');
  if (at < 0) return null;
  try { const j = JSON.parse(m.slice(at)); return j && typeof j.message === 'string' && j.message ? j.message : null; } catch { return null; }
}
