/* Tests for the per-screen loads (src/lib/querycache.ts), run the way React runs them: every part
 * of the page asks for its query after each render, and each redraw renders every part again.
 * A client page has two document fields reading the same documents list; each start of
 * a load redrew the page, the redraw asked again, and the page crashed (React error #185).
 * Node runs the .ts file as it is (Node 22.18 or newer). Run: npm test */
import assert from 'node:assert/strict';

if (!process.features.typescript) {
  console.log('Query tests skipped: they need Node 22.18 or newer (this is ' + process.version + ').');
  process.exit(0);
}
const Q = await import('../src/lib/querycache.ts');

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const settle = () => new Promise((r) => setTimeout(r, 0));

/** A page of parts that each ask for one spec after every render. Each notify() = one redraw.
 *  Returns the number of renders until it stops (or the cap, which means it never stops). */
function page({ specs, load, cap = 50, now }) {
  let redraws = 0;
  const loads = [];
  const cache = Q.queryCache({
    load: (spec) => { loads.push(spec.key); return load(spec); },
    notify: () => { redraws++; },
    isMissing: (err) => /does not exist/.test(String(err && err.message)),
    now,
  });
  const render = () => { specs().forEach((s) => cache.ensure(s)); };
  /** Render once, then again for every redraw it caused, the way React would. */
  const run = () => {
    let renders = 0;
    do { redraws = 0; render(); renders++; } while (redraws > 0 && renders < cap);
    return renders;
  };
  return { cache, loads, run };
}

/* The client page's document query (lib/documents.ts docsSpec): a new object on every render,
 * the same key. */
const clientDocs = () => ({ key: 'docs:c-north:-:-', table: 'documents', ttl: 30000, acceptsInserts: false,
  opts: { select: 'id,field_key', filter: 'client_id=eq.c-north&board=is.null&card_id=is.null' } });

test('a client page with two document fields loads once and stops redrawing', async () => {
  let answer;
  const p = page({ specs: () => [clientDocs(), clientDocs()], load: () => new Promise((r) => { answer = r; }) });
  const first = p.run();
  assert.ok(first < 5, 'renders while the load runs: ' + first);
  assert.equal(p.loads.length, 1);
  /* More renders while the load still runs (any other change on the page) start nothing. */
  assert.ok(p.run() < 5);
  assert.equal(p.loads.length, 1);
  answer({ rows: [{ id: 'd1', field_key: 'offer_doc' }] });
  await settle();
  assert.ok(p.run() < 5);
  assert.equal(p.loads.length, 1);
  const q = p.cache.map.get('docs:c-north:-:-');
  assert.deepEqual([q.loading, q.rows.length], [false, 1]);
});

test('the same with a load that fails (no documents table yet): one try, then it says so', async () => {
  let fail;
  const p = page({ specs: () => [clientDocs(), clientDocs()], load: () => new Promise((_, r) => { fail = r; }) });
  assert.ok(p.run() < 5);
  fail(new Error('relation "documents" does not exist'));
  await settle();
  assert.ok(p.run() < 5);
  assert.equal(p.loads.length, 1);
  const q = p.cache.map.get('docs:c-north:-:-');
  assert.deepEqual([q.loading, q.missing, q.rows.length], [false, true, 0]);
});

test('a load is read again only after its ttl; force reads again, but not while a load runs', async () => {
  let t = 1000;
  const answers = [];
  const p = page({ specs: () => [clientDocs()], load: () => new Promise((r) => answers.push(r)), now: () => t });
  p.run();
  answers[0]({ rows: [] }); await settle();
  t += 10000; p.run();
  assert.equal(p.loads.length, 1, 'younger than 30 s: reused');
  t += 30000; p.run();
  assert.equal(p.loads.length, 2, 'older: read again');
  p.cache.ensure(clientDocs(), true);
  assert.equal(p.loads.length, 2, 'force while a load runs starts nothing');
  answers[1]({ rows: [] }); await settle();
  p.cache.ensure(clientDocs(), true);
  assert.equal(p.loads.length, 3, 'force after it ends reads again');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
