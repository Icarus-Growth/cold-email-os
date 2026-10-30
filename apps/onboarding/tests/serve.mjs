/* ============================================================================
   The form on your own computer, on a throwaway database.

   Runs the real worker and the real page at http://localhost:8787, against a
   Postgres in memory made from this repo's change files and example rows
   (tests/postgrest.mjs). Nothing reaches Supabase or Cloudflare, and every
   answer is gone when you stop it.

   Run (from apps/onboarding, after npm install):  npm run dev
   It prints one form link for each example client.
   ========================================================================= */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { makeDatabase } from "./postgrest.mjs";
import { buildWorker, ENV, REPO } from "./link.test.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, "..", "site");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css" };

const ASSETS = {
  async fetch(req) {
    let p = decodeURIComponent(new URL(req.url).pathname);
    if (p.endsWith("/")) p += "index.html";
    const file = path.join(SITE, p);
    if (!file.startsWith(SITE + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      return new Response("not found", { status: 404 });
    }
    return new Response(fs.readFileSync(file), { status: 200, headers: { "Content-Type": TYPES[path.extname(file)] || "text/plain" } });
  },
};

/* Starts the server. Returns {url, data, close}. */
export async function startServer({ port = 8787, examples = true } = {}) {
  const data = await makeDatabase(REPO);
  if (examples) {
    const ex = path.join(REPO, "docs/examples/add_examples.sql");
    if (fs.existsSync(ex)) {
      await data.db.exec("reset role");
      await data.db.exec(fs.readFileSync(ex, "utf8"));
      await data.db.exec("set role service_role");
    }
  }
  const told = [];
  globalThis.fetch = data.makeFetch(async (url, init) => {
    told.push({ url: String(url), body: init && init.body });
    return new Response("{}", { status: 200 });
  });
  const { worker } = await buildWorker();
  const env = { ...ENV, ASSETS };

  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const request = new Request("http://" + req.headers.host + req.url, {
      method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body,
    });
    const waits = [];
    const out = await worker.fetch(request, env, { waitUntil: (p) => waits.push(p) });
    res.writeHead(out.status, Object.fromEntries(out.headers.entries()));
    res.end(Buffer.from(await out.arrayBuffer()));
    await Promise.all(waits);
  });
  await new Promise((r) => server.listen(port, "127.0.0.1", r));
  const url = "http://127.0.0.1:" + server.address().port;
  return { url, data, told, close: () => new Promise((r) => server.close(r)) };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { url, data } = await startServer({ port: Number(process.env.PORT || 8787) });
  const clients = await data.query("select client_name, form_code from clients order by client_name");
  console.log(`\nThe onboarding form is running on a throwaway database at ${url}\n`);
  console.log(`  New client (no code):  ${url}/form`);
  for (const c of clients) console.log(`  ${c.client_name}:  ${url}/form/${c.form_code}`);
  console.log("\nPress Ctrl+C to stop. Every answer is deleted when it stops.\n");
}
