/* ============================================================================
   A stand-in for the Supabase web API, on a real Postgres in memory (PGlite).

   It loads this repo's own change files (apps/os/backend/supabase/migrations),
   so the form is tested against the real tables, the real triggers, the real
   unique rules and the real grants. It answers only the small part of the
   Supabase web API (PostgREST) that worker/worker.js uses:

     GET    /rest/v1/<table>?col=eq.x&col=is.null&select=a,b&limit=n&order=c.desc
     POST   /rest/v1/<table>[?on_conflict=a,b]   Prefer: resolution=ignore-duplicates
     PATCH  /rest/v1/<table>?<filters>           Prefer: return=representation|minimal

   Filters: eq, neq, lt, lte, gt, gte, is (null, true, false), in.(a,b).
   Every request runs as the service_role, which is what the secret key is.

   Each request waits 1 to 3 ms before it runs, as a real network does, so two
   requests at the same moment interleave the way they do for real.
   ========================================================================= */

import fs from "node:fs";
import path from "node:path";

export const SUPABASE_URL = "https://test-project.supabase.example";
const REST = SUPABASE_URL + "/rest/v1/";

/* The same Supabase stand-ins as tools/sqltest/run.mjs in the working repo. */
const STUBS = `
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  create schema auth; create schema extensions;
  create function auth.jwt() returns jsonb language sql stable as $$
    select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
  grant usage on schema public, auth to anon, authenticated, service_role;
  grant execute on function auth.jwt() to anon, authenticated;
  alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
  alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
  alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;
`;

const ident = (s) => {
  if (!/^[a-z_][a-z0-9_]*$/.test(s)) throw Object.assign(new Error("bad name " + s), { status: 400 });
  return '"' + s + '"';
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function makeDatabase(repoRoot) {
  const { PGlite } = await import("@electric-sql/pglite");
  const db = new PGlite();
  await db.exec(STUBS);
  const mig = path.join(repoRoot, "apps/os/backend/supabase/migrations");
  const files = fs.readdirSync(mig).filter((f) => f.endsWith(".sql")).sort();
  for (const f of files) await db.exec(fs.readFileSync(path.join(mig, f), "utf8"));
  await db.exec("set role service_role");

  const typesCache = {};
  async function columns(table) {
    if (!typesCache[table]) {
      const rows = (await db.query(
        `select a.attname as name, format_type(a.atttypid, a.atttypmod) as type
           from pg_attribute a join pg_class c on c.oid = a.attrelid join pg_namespace n on n.oid = c.relnamespace
          where n.nspname = 'public' and c.relname = $1 and a.attnum > 0 and not a.attisdropped`, [table])).rows;
      if (!rows.length) throw Object.assign(new Error("no table " + table), { status: 404, code: "42P01" });
      typesCache[table] = Object.fromEntries(rows.map((r) => [r.name, r.type]));
    }
    return typesCache[table];
  }

  /* ?col=op.value ... -> a SQL where clause, with its values as parameters. */
  function where(params, cols, values) {
    const parts = [];
    const add = (v) => { values.push(v); return "$" + values.length; };
    for (const [k, raw] of params) {
      if (["select", "limit", "order", "on_conflict", "columns"].includes(k)) continue;
      if (!(k in cols)) throw Object.assign(new Error("no column " + k), { status: 400, code: "42703" });
      const m = /^(not\.)?(eq|neq|lt|lte|gt|gte|is|in)\.(.*)$/s.exec(raw);
      if (!m) throw Object.assign(new Error("bad filter " + k + "=" + raw), { status: 400, code: "PGRST100" });
      const [, not, op, arg] = m;
      const col = "t." + ident(k), type = cols[k];
      let sql;
      if (op === "is") {
        if (!["null", "true", "false"].includes(arg)) throw Object.assign(new Error("bad is"), { status: 400 });
        sql = `${col} is ${arg}`;
      } else if (op === "in") {
        const list = arg.replace(/^\(|\)$/g, "").split(",").map((s) => s.replace(/^"|"$/g, ""));
        sql = `${col} = any(${add(list)}::${type}[])`;
      } else {
        const sym = { eq: "=", neq: "<>", lt: "<", lte: "<=", gt: ">", gte: ">=" }[op];
        sql = `${col} ${sym} ${add(arg)}::${type}`;
      }
      parts.push(not ? `not (${sql})` : sql);
    }
    return parts.length ? " where " + parts.join(" and ") : "";
  }

  async function handle(method, url, headers, body) {
    const u = new URL(url);
    const table = decodeURIComponent(u.pathname.slice("/rest/v1/".length));
    if (table.startsWith("rpc/")) throw Object.assign(new Error("no function " + table), { status: 404, code: "PGRST202" });
    const cols = await columns(table);
    const params = [...u.searchParams.entries()];
    const prefer = String(headers.Prefer || headers.prefer || "");
    const values = [];
    const T = "public." + ident(table);

    if (method === "GET") {
      const sel = u.searchParams.get("select");
      const list = !sel || sel === "*" ? "t.*" : sel.split(",").map((c) => {
        if (!(c in cols)) throw Object.assign(new Error("no column " + c), { status: 400, code: "42703" });
        return "t." + ident(c);
      }).join(", ");
      let sql = `select ${list} from ${T} t` + where(params, cols, values);
      const order = u.searchParams.get("order");
      if (order) {
        sql += " order by " + order.split(",").map((o) => {
          const [c, dir] = o.split(".");
          if (!(c in cols)) throw Object.assign(new Error("no column " + c), { status: 400 });
          return "t." + ident(c) + (dir === "desc" ? " desc" : " asc");
        }).join(", ");
      }
      const limit = u.searchParams.get("limit");
      if (limit) sql += " limit " + Number(limit);
      const rows = (await db.query(`select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) as j from (${sql}) x`, values)).rows;
      return { status: 200, body: rows[0].j };
    }

    if (method === "POST") {
      const items = Array.isArray(body) ? body : [body];
      const keys = [...new Set(items.flatMap((i) => Object.keys(i)))];
      for (const k of keys) if (!(k in cols)) throw Object.assign(new Error("no column " + k), { status: 400, code: "PGRST204" });
      const list = keys.map(ident).join(", ");
      let sql = `insert into ${T} (${list}) select ${keys.map((k) => "r." + ident(k)).join(", ")} ` +
        `from jsonb_populate_recordset(null::${T}, $1) r`;
      values.push(JSON.stringify(items));
      const oc = u.searchParams.get("on_conflict");
      if (/resolution=ignore-duplicates/.test(prefer)) {
        sql += oc ? ` on conflict (${oc.split(",").map(ident).join(", ")}) do nothing` : " on conflict do nothing";
      }
      const rows = (await db.query(`with ins as (${sql} returning *) select coalesce(jsonb_agg(to_jsonb(ins)), '[]'::jsonb) as j from ins`, values)).rows;
      return { status: 201, body: /return=representation/.test(prefer) ? rows[0].j : null };
    }

    if (method === "PATCH") {
      const keys = Object.keys(body || {});
      if (!keys.length) throw Object.assign(new Error("empty patch"), { status: 400 });
      for (const k of keys) if (!(k in cols)) throw Object.assign(new Error("no column " + k), { status: 400, code: "PGRST204" });
      values.push(JSON.stringify(body));
      const set = keys.map((k) => `${ident(k)} = r.${ident(k)}`).join(", ");
      const sql = `update ${T} t set ${set} from jsonb_populate_record(null::${T}, $1) r` + where(params, cols, values);
      const rows = (await db.query(`with up as (${sql} returning t.*) select coalesce(jsonb_agg(to_jsonb(up)), '[]'::jsonb) as j from up`, values)).rows;
      return { status: /return=representation/.test(prefer) ? 200 : 204, body: /return=representation/.test(prefer) ? rows[0].j : null };
    }

    throw Object.assign(new Error("method " + method), { status: 405 });
  }

  const calls = { rest: 0 };
  /* A fetch() for the worker: Supabase calls come here, anything else goes to `other`. */
  function makeFetch(other) {
    return async function fakeFetch(input, init = {}) {
      const url = typeof input === "string" ? input : input.url;
      if (!String(url).startsWith(REST)) {
        if (other) return other(url, init);
        throw new Error("unexpected fetch: " + url);
      }
      calls.rest += 1;
      const headers = init.headers || {};
      if (!String(headers.apikey || "").length) return new Response(JSON.stringify({ message: "no apikey" }), { status: 401 });
      await sleep(1 + Math.random() * 2);
      try {
        const body = init.body ? JSON.parse(init.body) : null;
        const res = await handle(init.method || "GET", url, headers, body);
        await sleep(1 + Math.random() * 2);
        return new Response(res.body === null ? null : JSON.stringify(res.body), {
          status: res.status, headers: { "Content-Type": "application/json" } });
      } catch (e) {
        const code = e.code || "";
        const status = e.status || (code === "23505" ? 409 : /^(22|23|42)/.test(code) ? 400 : 500);
        return new Response(JSON.stringify({ code, message: e.message, details: e.detail || null }), {
          status, headers: { "Content-Type": "application/json" } });
      }
    };
  }

  return { db, makeFetch, calls, query: async (sql, p) => (await db.query(sql, p)).rows };
}
