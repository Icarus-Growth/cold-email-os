/* The database (Supabase's REST API). No client library.
 *
 * Every request carries the signed-in person's access token (lib/auth.ts), and waits for it
 * to be refreshed first when it is nearly spent. The team-only rules in the database decide
 * what that token can do: a person who is not on the team gets no rows at all.
 *
 * Writes: update / insert return the row the database now holds
 * (Prefer: return=representation), not the row we asked it to hold.
 *
 * Screens never call this file directly: they go through lib/store.ts.
 */
import { CONFIG } from './config';
import * as Auth from './auth';

export type Row = Record<string, any> & { id: string };

export interface SelectOpts {
  /** Select list. Default '*'. */
  select?: string;
  /** Order, e.g. 'updated_at.desc' or 'client_name.asc'. */
  order?: string;
  /** Extra raw query-string filters, e.g. 'client_id=eq.<id>'. */
  filter?: string;
  limit?: number;
  offset?: number;
}

export const MAX_ROWS = 500; // the most rows one request asks for

/** Tables read by named columns, never '*'. The team table hides one column from browsers
 *  (the AI link's hash, migration 0010), and a '*' read or write of a table with a hidden
 *  column fails as a whole. A column added to team later must be added here to show. */
export const READ_COLUMNS: Record<string, string> = {
  team: 'id,full_name,email,job_title,access,status,can_sign_in,capacity,slack_user_id,phone,notes,is_example,created_at,updated_at,mcp_last_seen_at',
};

function headers(extra?: Record<string, string>): Record<string, string> {
  return { apikey: CONFIG.SUPABASE_PUBLISHABLE_KEY, Authorization: 'Bearer ' + Auth.token(), ...(extra || {}) };
}

async function fail(table: string, res: Response): Promise<never> {
  // 401: the session is gone (revoked, or refresh failed). Back to sign-in.
  if (res.status === 401) Auth.expired();
  const t = await res.text();
  throw new Error(table + ': HTTP ' + res.status + ' ' + t.slice(0, 300));
}

/** One page of a table. */
export async function select(table: string, opts: SelectOpts = {}): Promise<{ rows: Row[]; total: number }> {
  const limit = Math.min(opts.limit || MAX_ROWS, MAX_ROWS);
  const offset = opts.offset || 0;
  const qs = ['select=' + encodeURIComponent(opts.select || READ_COLUMNS[table] || '*')];
  if (opts.order) qs.push('order=' + encodeURIComponent(opts.order));
  if (opts.filter) qs.push(opts.filter);
  const url = CONFIG.SUPABASE_URL + '/rest/v1/' + table + '?' + qs.join('&');
  await Auth.fresh();
  const res = await fetch(url, { headers: headers({ Range: offset + '-' + (offset + limit - 1), Prefer: 'count=exact' }) });
  if (!res.ok) return fail(table, res);
  let total: number | null = null;
  const cr = res.headers.get('content-range');
  if (cr && cr.indexOf('/') > -1) {
    const tail = cr.split('/')[1];
    if (tail !== '*') total = parseInt(tail, 10);
  }
  const rows = (await res.json()) as Row[];
  return { rows, total: total === null ? rows.length : total };
}

/** Walk a table in pages of 500 until it ends or `cap` rows are held. */
export async function selectAll(table: string, opts: SelectOpts = {}, cap = 5000): Promise<{ rows: Row[]; total: number }> {
  let acc: Row[] = [];
  let offset = 0;
  for (;;) {
    const r = await select(table, { ...opts, offset, limit: MAX_ROWS });
    acc = acc.concat(r.rows);
    if (r.rows.length === MAX_ROWS && acc.length < cap && acc.length < r.total) { offset += MAX_ROWS; continue; }
    return { rows: acc, total: r.total };
  }
}

async function write(method: 'PATCH' | 'POST' | 'DELETE', table: string, path: string, body: unknown): Promise<Row | null> {
  // The row that comes back names its columns too, for the same reason as a read.
  const cols = READ_COLUMNS[table] ? 'select=' + encodeURIComponent(READ_COLUMNS[table]) : '';
  const qs = [path, cols].filter(Boolean).join('&');
  const url = CONFIG.SUPABASE_URL + '/rest/v1/' + table + (qs ? '?' + qs : '');
  await Auth.fresh();
  const res = await fetch(url, {
    method,
    headers: headers({ 'Content-Type': 'application/json', Prefer: 'return=representation' }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) return fail(table, res);
  if (res.status === 204) return null;
  const rows = await res.json();
  return Array.isArray(rows) ? rows[0] || null : rows;
}

/** Change one row by id; resolves with the row the database now holds. */
export function update(table: string, id: string, patch: Record<string, unknown>): Promise<Row | null> {
  return write('PATCH', table, 'id=eq.' + encodeURIComponent(id), patch);
}

/** Add one row; resolves with the row the database made. */
export function insert(table: string, row: Record<string, unknown>): Promise<Row | null> {
  return write('POST', table, '', row);
}

/** Delete one row by id; resolves with the row the database removed (null if there was none). */
export function remove(table: string, id: string): Promise<Row | null> {
  return write('DELETE', table, 'id=eq.' + encodeURIComponent(id), undefined);
}

/** Run a database function (POST /rest/v1/rpc/<name>) as the signed-in person. */
export async function rpc(name: string, args: Record<string, unknown>): Promise<unknown> {
  await Auth.fresh();
  const res = await fetch(CONFIG.SUPABASE_URL + '/rest/v1/rpc/' + name, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(args),
  });
  if (!res.ok) return fail(name, res);
  const t = await res.text();
  return t ? JSON.parse(t) : null;
}

/** True when an error means the table or view is not there yet (a change file not applied). */
export function isMissingTable(err: unknown): boolean {
  return /42P01|42883|PGRST202|PGRST205|does not exist|404|schema cache/.test(String(err && (err as Error).message));
}
