/* The per-screen loads behind useQuery (lib/store.ts): one entry per key, read again when it is
 * older than its ttl.
 *
 * A load in flight is never started again. Many parts of one page can ask for the same key (a
 * client page has one document field per document, each reading the same documents list):
 * each asks on every render, and each new start redraws the page, so starting again while a
 * load runs would redraw for ever (React error #185).
 *
 * No imports but types: tests/queries.test.mjs runs this file in Node as it is. */
import type { Row, SelectOpts } from './db';

export interface Query {
  table: string;
  rows: Row[] | null;     // null until the first load lands
  loading: boolean;
  error: string | null;
  missing: boolean;       // the table or view does not exist yet (a change file not applied)
  at: number;             // when it last loaded (ms)
  acceptsInserts: boolean;
  spec?: QuerySpec;
}

export interface QuerySpec {
  /** Cache key, unique per table + filter. */
  key: string;
  table: string;
  opts?: SelectOpts;
  /** Reuse a load younger than this many ms. 0 = fetch fresh on every visit. Default 30000. */
  ttl?: number;
  /** Rows inserted on this table join this list. Default: true when unfiltered. */
  acceptsInserts?: boolean;
}

export const EMPTY_QUERY: Query = { table: '', rows: null, loading: true, error: null, missing: false, at: 0, acceptsInserts: false };

export interface QueryCache {
  map: Map<string, Query>;
  /** Store a query; redraw unless `quiet`. */
  set(key: string, q: Query, quiet?: boolean): void;
  /** Load (or reuse) one query. `force` reads again unless a load is already running. */
  ensure(spec: QuerySpec, force?: boolean): Query;
}

export function queryCache(o: {
  load: (spec: QuerySpec) => Promise<{ rows: Row[] }>;
  notify: () => void;
  isMissing: (err: unknown) => boolean;
  now?: () => number;
}): QueryCache {
  const map = new Map<string, Query>();
  const now = o.now || Date.now;
  const set = (key: string, q: Query, quiet = false) => { map.set(key, q); if (!quiet) o.notify(); };
  function ensure(spec: QuerySpec, force = false): Query {
    const ttl = spec.ttl === undefined ? 30000 : spec.ttl;
    const q = map.get(spec.key);
    if (q && q.loading) return q;
    if (q && !force && q.at && now() - q.at < ttl) return q;
    const next: Query = { table: spec.table, rows: q ? q.rows : null, loading: true, error: null, missing: false,
                          at: q ? q.at : 0, acceptsInserts: spec.acceptsInserts ?? !(spec.opts && spec.opts.filter), spec };
    set(spec.key, next, !q);
    o.load(spec).then((r) => {
      set(spec.key, { ...map.get(spec.key)!, rows: r.rows, loading: false, error: null, missing: false, at: now() });
    }).catch((err) => {
      const cur = map.get(spec.key)!;
      set(spec.key, { ...cur, rows: cur.rows || [], loading: false,
                      error: String((err && err.message) || err), missing: o.isMissing(err), at: now() });
    });
    return next;
  }
  return { map, set, ensure };
}
