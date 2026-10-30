/* The data the screens read, and the only way they write.
 *
 * READ
 *   useData()            the core tables (team, clients, settings, every board, every list,
 *                        every checklist), loaded once at start, shaped (by-id maps,
 *                        client colours, the signed-in person)
 *   useQuery(...)        a per-screen load (calls, forms, numbers, the dashboard views),
 *                        cached 30s unless asked to be fresh
 *
 * WRITE
 *   patch(table, id, fields)  shows the change at once; puts it back and says so if the save fails
 *   move(table, id, stage)    a board's stage change (the database writes the stage log by itself)
 *   insert(table, row)        the "New X" forms
 *   remove(table, id)         "Delete" at the top of a record
 *   Each renders the row the database returned, then reloads the core tables 700ms later.
 *
 * FRESH
 *   The page reads everything again once a minute while it is open and in view, and
 *   whenever the tab comes back into view. While a pointer is down or a card is being
 *   dragged nothing re-renders; the update lands when it is released. Text being typed is
 *   never touched: the editors keep their own draft while focused (ui/Inputs.tsx, ui/RichText.tsx).
 */
import { useEffect, useSyncExternalStore } from 'react';
import * as DB from './db';
import type { Row, SelectOpts } from './db';
import * as Auth from './auth';
import { CHECKLIST_TABLES, RECORDS, recordDef } from './schema';
import { toast } from './ui';
import { tinyStore } from './tinyStore';
import { EMPTY_QUERY, queryCache, type Query, type QuerySpec } from './querycache';

export type { Row };

/* ---------- load --------------------------------------------------------- */

/** The core tables, with the order each is read in. */
const CORE: Array<[string, SelectOpts]> = [
  ['team', { order: 'full_name' }],
  ['clients', { order: 'client_name' }],
  ['settings', {}],
  ...RECORDS.map((r): [string, SelectOpts] => [r.table, { order: 'updated_at.desc' }]),
  ...CHECKLIST_TABLES.map((t): [string, SelectOpts] => [t, { order: 'position.asc,created_at.asc' }]),
];

export type Raw = Record<string, Row[]>;

let raw: Raw | null = null;
let version = 0;
let shapedAt = -1;
let shaped: Data | null = null;

/* ---------- re-render, but never mid-click or mid-drag ------------------- */

const subs = new Set<() => void>();
let pressing = false;
let dragging = false;
let pending = false;

function notify() {
  if (pressing || dragging) { pending = true; return; }
  pending = false;
  subs.forEach((f) => f());
}
/** The core tables changed. */
function emit() { version += 1; notify(); }
function flush() {
  if (pending && !pressing && !dragging) { pending = false; subs.forEach((f) => f()); }
}
if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', () => { pressing = true; }, true);
  const released = () => { if (!pressing) return; pressing = false; setTimeout(flush, 0); };
  document.addEventListener('pointerup', released, true);
  document.addEventListener('pointercancel', released, true);
  window.addEventListener('blur', released);
}
/** The board calls this while a card is held, so nothing redraws under it. */
export function setDragging(on: boolean) { dragging = on; if (!on) setTimeout(flush, 0); }

function subscribe(fn: () => void) { subs.add(fn); return () => { subs.delete(fn); }; }
const snap = () => version;

/** Load the core tables (boot, and the reconcile after every write). */
export async function loadAll(): Promise<Data> {
  const r = await Promise.all(CORE.map((t) => DB.selectAll(t[0], t[1]).catch((err) => {
    // A board whose change file is not applied yet must not stop the whole OS.
    if (DB.isMissingTable(err)) { console.warn('[os] ' + t[0] + ' is not in the database yet.'); return { rows: [] as Row[], total: 0 }; }
    throw err;
  })));
  const next: Raw = {};
  CORE.forEach((t, i) => { next[t[0]] = r[i].rows; });
  raw = next;
  emit();
  return current()!;
}

/** The shaped data right now (null before the first load). */
export function current(): Data | null {
  if (!raw) return null;
  if (shapedAt !== version || !shaped) { shaped = shape(raw); shapedAt = version; }
  return shaped;
}

/** The shaped core data. Re-renders on every change. Only call under the shell (data is loaded). */
export function useData(): Data {
  useSyncExternalStore(subscribe, snap, snap);
  return current()!;
}

/* ---------- applying a change in place ------------------------------------ */

function findIn(list: Row[], id: string) { for (let i = 0; i < list.length; i++) if (list[i].id === id) return i; return -1; }

/** Fold a row change into the core tables and every cached query. */
export function applyChange(ch: { table: string; type: 'INSERT' | 'UPDATE' | 'DELETE'; row: Row | null; old?: Row | null }): boolean {
  const id = (ch.row && ch.row.id) || (ch.old && ch.old.id);
  if (!id) return false;
  let hit = false;
  let core = false;
  if (raw && raw[ch.table]) {
    const list = raw[ch.table].slice();
    const at = findIn(list, id);
    if (ch.type === 'DELETE') { if (at > -1) list.splice(at, 1); }
    else if (at > -1) list[at] = { ...list[at], ...ch.row };
    else if (ch.row) list.unshift(ch.row);
    raw = { ...raw, [ch.table]: list };
    hit = true; core = true;
  }
  queries.forEach((q, key) => {
    if (q.table !== ch.table || !q.rows) return;
    const at = findIn(q.rows, id);
    if (at < 0 && ch.type !== 'INSERT') return;
    const rows = q.rows.slice();
    if (ch.type === 'DELETE') rows.splice(at, 1);
    else if (at > -1) rows[at] = { ...rows[at], ...ch.row };
    else if (ch.row && q.acceptsInserts) rows.unshift(ch.row);
    else return;
    setQuery(key, { ...q, rows });
    hit = true;
  });
  if (core) emit(); else if (hit) notify();
  return hit;
}

function rowNow(table: string, id: string): Row | null {
  if (raw && raw[table]) { const at = findIn(raw[table], id); if (at > -1) return raw[table][at]; }
  let found: Row | null = null;
  queries.forEach((q) => {
    if (found || q.table !== table || !q.rows) return;
    const at = findIn(q.rows, id);
    if (at > -1) found = q.rows[at];
  });
  return found;
}

/* ---------- writes ---------------------------------------------------------- */

/** Columns the database fills. The page never writes them. */
const NEVER_WRITE = /^(id|created_at|updated_at|is_example|form_code|archived_at)$|^mcp_|_changed_at$|_changed_by_id$|_rate$|^cost_per_lead$/;

const saving = tinyStore(0);
/** How many saves are in flight (the "Saving…" line). */
export function useSaving(): number { return saving.use(); }

let reconcileTimer: ReturnType<typeof setTimeout> | undefined;
function reconcile() {
  clearTimeout(reconcileTimer);
  reconcileTimer = setTimeout(() => { loadAll().catch(() => {}); }, 700);
}

/** A database refusal in words a person can act on; anything else as it came. */
export function saveError(err: unknown): string {
  const m = String((err as Error)?.message || err);
  if (/23505/.test(m)) return 'That is already there. It must be unique.';
  if (/23502/.test(m)) return 'A field that must be filled is empty.';
  if (/42501/.test(m)) return 'You are not allowed to change that.';
  if (/23514|22P02/.test(m)) return 'That value is not allowed here.';
  if (/22007|22008/.test(m)) return 'That is not a date the database understands.';
  return m;
}

function guard(table: string, fields: Record<string, unknown>) {
  const bad = Object.keys(fields).filter((k) => NEVER_WRITE.test(k));
  if (!bad.length) return;
  const msg = 'The database fills ' + bad.join(', ') + ' on ' + table + '. The page may not write it.';
  console.error('[os] refused write: ' + msg);
  toast('That did not save: ' + msg, 'bad');
  throw new Error(msg);
}

/** Save some fields on one row. Shows the change at once; puts it back and says so if the save fails. */
export async function patch(table: string, id: string, fields: Record<string, unknown>): Promise<Row | null> {
  guard(table, fields);
  const before = rowNow(table, id);
  const undo: Record<string, unknown> = {};
  if (before) Object.keys(fields).forEach((k) => { undo[k] = before[k]; });
  if (before) applyChange({ table, type: 'UPDATE', row: { ...before, ...fields } as Row });
  saving.set((n) => n + 1);
  try {
    const row = await DB.update(table, id, fields);
    if (row) applyChange({ table, type: 'UPDATE', row });
    reconcile();
    return row;
  } catch (err) {
    const now = rowNow(table, id);
    if (now && before) applyChange({ table, type: 'UPDATE', row: { ...now, ...undo } as Row });
    toast('That did not save: ' + saveError(err), 'bad');
    throw err;
  } finally {
    saving.set((n) => Math.max(0, n - 1));
  }
}

/** Move a card to another stage. The card lands at once; only a failure moves it back. */
export async function move(table: string, id: string, stage: string): Promise<Row | null> {
  const def = recordDef(table);
  if (!def) throw new Error(table + ' has no stages');
  const card = rowNow(table, id);
  if (!card || card[def.stageKey] === stage) return card;
  return patch(table, id, { [def.stageKey]: stage });
}

/** Add one row (the "New X" forms). */
export async function insert(table: string, row: Record<string, unknown>): Promise<Row | null> {
  guard(table, row);
  saving.set((n) => n + 1);
  try {
    const made = await DB.insert(table, row);
    if (made) applyChange({ table, type: 'INSERT', row: made });
    reconcile();
    return made;
  } catch (err) {
    toast('That did not save: ' + saveError(err), 'bad');
    throw err;
  } finally {
    saving.set((n) => Math.max(0, n - 1));
  }
}

/** Delete one row. It goes at once; it comes back and the page says so if the delete fails. */
export async function remove(table: string, id: string): Promise<Row | null> {
  const before = rowNow(table, id);
  if (before) applyChange({ table, type: 'DELETE', row: null, old: before });
  saving.set((n) => n + 1);
  try {
    const gone = await DB.remove(table, id);
    reconcile();
    return gone;
  } catch (err) {
    if (before) applyChange({ table, type: 'INSERT', row: before });
    toast('That did not delete: ' + saveError(err), 'bad');
    throw err;
  } finally {
    saving.set((n) => Math.max(0, n - 1));
  }
}

/* ---------- per-screen loads ------------------------------------------------ */

export type { Query, QuerySpec };
const cache = queryCache({ load: (spec) => DB.selectAll(spec.table, spec.opts || {}), notify: () => notify(), isMissing: DB.isMissingTable });
const queries = cache.map;
const setQuery = cache.set;

/** Load (or reuse) one per-screen query (lib/querycache.ts: a load in flight is never started again). */
export function ensureQuery(spec: QuerySpec, force = false): Query {
  return cache.ensure(spec, force);
}

/** React hook: one per-screen load and its state. Pass null to load nothing. */
export function useQuery(spec: QuerySpec | null): Query {
  const key = spec ? spec.key : '';
  const get = () => (spec ? queries.get(key) || EMPTY_QUERY : EMPTY_QUERY);
  const q = useSyncExternalStore(subscribe, get, get);
  useEffect(() => { if (spec && spec.ttl === 0) ensureQuery(spec, true); }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (spec && spec.ttl !== 0) ensureQuery(spec); });
  return q;
}

/* ---------- archive a client ---------------------------------------------------
 * The database does it (archive_client / restore_client, migration 0010), for an Owner or
 * Admin only: the client and every card it has get the same archived_at, and restore brings
 * back only what that archive took. Nothing is deleted. */

async function clientArchive(fn: 'archive_client' | 'restore_client', clientId: string, done: string): Promise<void> {
  saving.set((n) => n + 1);
  try {
    await DB.rpc(fn, { p_client: clientId });
    await loadAll();
    toast(done, 'good');
  } catch (err) {
    toast('That did not work: ' + saveError(err), 'bad');
    throw err;
  } finally {
    saving.set((n) => n - 1);
  }
}

/** Archive a client and its cards. */
export function archiveClient(clientId: string): Promise<void> {
  return clientArchive('archive_client', clientId, 'Archived. The client and its cards are hidden.');
}
/** Bring an archived client back, with the cards its archive took. */
export function restoreClient(clientId: string): Promise<void> {
  return clientArchive('restore_client', clientId, 'Restored. The client and its cards are back.');
}

/** True when a row is archived (it has an archived_at time). */
export function isArchived(row: Row | null | undefined): boolean { return !!(row && row.archived_at); }

/* ---------- staying fresh ---------------------------------------------------- */

export const REFRESH_MS = 60000;
let lastTick = 0;

/** Read everything the page holds again: the core tables, then every per-screen query. */
export async function refreshAll(): Promise<void> {
  if (typeof document !== 'undefined' && document.hidden) return;
  lastTick = Date.now();
  await loadAll().catch(() => {});
  queries.forEach((q) => { if (q.spec && !q.loading && !q.missing) ensureQuery(q.spec, true); });
}

/** Start the once-a-minute refresh, and refresh when the tab comes back into view. */
export function startRefresh(): void {
  setInterval(() => { refreshAll(); }, REFRESH_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - lastTick > 10000) refreshAll();
  });
}

/* ---------- shape ---------------------------------------------------------------- */

function by(list: Row[]): Record<string, Row> {
  const m: Record<string, Row> = {};
  for (const r of list) m[r.id] = r;
  return m;
}

/** The per-client chart colours (theme.css --os-c1..10), one per client, stable across pages. */
export const CLIENT_COLOURS = 10;

export interface Data {
  raw: Raw;
  /** The rows of a core table ([] when it is not loaded), without archived rows. */
  rows(table: string): Row[];
  /** The same, archived rows too (for "Show archived" and an archived client's page). */
  allRows(table: string): Row[];
  /** One row of a core table by id, or null. */
  row(table: string, id?: string | null): Row | null;
  clientById: Record<string, Row>;
  teamById: Record<string, Row>;
  /** Active clients that are not archived, in name order. */
  activeClients: Row[];
  /** Active team members, in name order. */
  activeTeam: Row[];
  /** The one settings row ({} before it exists). */
  settings: Row;
  /** The client's name for an id, '—' when unknown. */
  clientName(id?: string | null): string;
  /** A team member's name by id, or null. */
  teamName(id?: string | null): string | null;
  /** The signed-in person's team row (by email), or null when they are not on the team. */
  me: Row | null;
  /** True for an Owner or Admin. */
  isAdmin: boolean;
  /** CSS colour for a client: var(--os-cN), the same on every chart and card. */
  clientColour(id?: string | null): string;
  /** The agency's name: settings.agency_name, or 'Agency'. */
  agencyName: string;
}

function shape(d: Raw): Data {
  const team = d.team || [];
  const clients = d.clients || [];
  const clientById = by(clients);
  const teamById = by(team);
  const colourIndex: Record<string, number> = {};
  clients.slice().sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
    .forEach((c, i) => { colourIndex[c.id] = (i % CLIENT_COLOURS) + 1; });
  const em = Auth.email().toLowerCase();
  const me = em ? team.find((t) => String(t.email || '').toLowerCase() === em) || null : null;
  const maps: Record<string, Record<string, Row>> = {};
  const live: Record<string, Row[]> = {};
  const settings = (d.settings && d.settings[0]) || ({} as Row);
  return {
    raw: d,
    rows(table) {
      if (!live[table]) live[table] = (d[table] || []).filter((r) => !r.archived_at);
      return live[table];
    },
    allRows(table) { return d[table] || []; },
    row(table, id) {
      if (!id) return null;
      if (!maps[table]) maps[table] = by(d[table] || []);
      return maps[table][id] || null;
    },
    clientById, teamById,
    activeClients: clients.filter((c) => c.status === 'Active' && !c.archived_at),
    activeTeam: team.filter((t) => t.status === 'Active'),
    settings,
    clientName(id) { const c = id ? clientById[id] : null; return c ? c.client_name || 'Unnamed client' : '—'; },
    teamName(id) { return id && teamById[id] ? teamById[id].full_name : null; },
    me,
    isAdmin: !!me && (me.access === 'Owner' || me.access === 'Admin'),
    clientColour(id) { return 'var(--os-c' + ((id && colourIndex[id]) || 1) + ')'; },
    agencyName: String(settings.agency_name || '').trim() || 'Agency',
  };
}

