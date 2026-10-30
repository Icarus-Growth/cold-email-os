/* Tests for the two Team server steps (functions/api/team/add.js and resend.js).
 * No network: fetch is replaced by a fake Supabase and a fake automations app.
 * Run: npm test  (Node 18 or newer). */
import assert from 'node:assert/strict';
import { onRequestPost as add } from '../functions/api/team/add.js';
import { onRequestPost as resend } from '../functions/api/team/resend.js';
import { onRequestPost as ai, linkParts } from '../functions/api/team/ai.js';
import { tempPassword } from '../functions/_lib/team.js';

const SB = 'https://example.supabase.co';
const ENV = { SUPABASE_URL: SB, SUPABASE_SECRET_KEY: 'test-secret' };
const OWNER = { id: '11111111-1111-4111-8111-111111111111', full_name: 'Olive Owner', email: 'owner@example.com', access: 'Owner', status: 'Active', can_sign_in: true };
const ADMIN = { id: '22222222-2222-4222-8222-222222222222', full_name: 'Adam Admin', email: 'admin@example.com', access: 'Admin', status: 'Active', can_sign_in: true };
const MEMBER = { id: '33333333-3333-4333-8333-333333333333', full_name: 'Mia Member', email: 'member@example.com', access: 'Member', status: 'Active', can_sign_in: true };
const GONE = { id: '44444444-4444-4444-8444-444444444444', full_name: 'Gus Gone', email: 'gone@example.com', access: 'Member', status: 'Inactive', can_sign_in: false };

/** A fake Supabase: tokens map to emails, a team table, a set of logins. */
function fake(opts) {
  const o = opts || {};
  const team = (o.team || [OWNER, ADMIN, MEMBER, GONE]).map((r) => ({ ...r }));
  const logins = new Map((o.logins || []).map((e, i) => [e, { id: 'user-' + i, email: e }]));
  const calls = [];
  const tokens = { 'tok-owner': OWNER.email, 'tok-admin': ADMIN.email, 'tok-member': MEMBER.email, 'tok-stranger': 'stranger@example.com' };
  globalThis.fetch = async (url, init) => {
    const u = new URL(url);
    const method = (init && init.method) || 'GET';
    const body = init && init.body ? JSON.parse(init.body) : undefined;
    const headers = (init && init.headers) || {};
    calls.push({ url: u, method, body, headers });
    const ok = (data, status) => new Response(JSON.stringify(data), { status: status || 200 });
    if (u.origin !== SB) {
      if (u.pathname === '/mcp/token') {
        if (o.mcpDown) throw new TypeError('fetch failed');
        if (o.mcpError) return ok({ error: o.mcpError }, 403);
        if (body.action !== 'issue') return ok({ revoked: true });
        return ok(o.oldLink ? { url: u.origin + '/mcp/s/secret-link/' }
          : { server: u.origin + '/mcp/', key: 'secret-link', url: u.origin + '/mcp/s/secret-link/' });
      }
      if (o.slackFails) return new Response('no', { status: 500 });
      return ok({ ok: true });
    }
    if (u.pathname === '/auth/v1/user') {
      const email = tokens[String(headers.Authorization).replace('Bearer ', '')];
      return email ? ok({ id: 'x', email }) : ok({ msg: 'bad jwt' }, 401);
    }
    assert.equal(headers.apikey, 'test-secret', 'every other call uses the secret key');
    if (u.pathname === '/rest/v1/team' && method === 'GET') {
      const f = [...u.searchParams.entries()].find(([k]) => k === 'email' || k === 'id');
      const v = f[1].replace(/^eq\./, '');
      return ok(team.filter((r) => r[f[0]] === v).slice(0, 1));
    }
    if (u.pathname === '/rest/v1/team' && method === 'POST') {
      assert.equal(u.searchParams.get('on_conflict'), 'email');
      let row = team.find((r) => r.email === body.email);
      if (row) Object.assign(row, body); else { row = { id: '55555555-5555-4555-8555-555555555555', ...body }; team.push(row); }
      return ok([row], 201);
    }
    if (u.pathname === '/rest/v1/settings') return ok([{ agency_name: 'Test Agency', os_url: o.osUrl || null }]);
    if (u.pathname === '/auth/v1/admin/users' && method === 'POST') {
      if (logins.has(body.email)) return ok({ msg: 'A user with this email address has already been registered' }, 422);
      const user = { id: 'user-new', email: body.email, password: body.password, meta: body.user_metadata };
      logins.set(body.email, user);
      return ok(user);
    }
    if (u.pathname === '/auth/v1/admin/generate_link') return ok({ id: logins.get(body.email).id, email: body.email });
    if (u.pathname.startsWith('/auth/v1/admin/users/') && method === 'PUT') {
      const user = [...logins.values()].find((x) => x.id === u.pathname.split('/').pop());
      Object.assign(user, { password: body.password, meta: body.user_metadata });
      return ok(user);
    }
    throw new Error('unexpected call ' + method + ' ' + u.pathname);
  };
  return { team, logins, calls };
}

function req(path, token, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  return new Request('https://os.example.com/api/team/' + path, { method: 'POST', headers, body: JSON.stringify(body || {}) });
}

async function run(fn, path, token, body, env) {
  const res = await fn({ request: req(path, token, body), env: env || ENV });
  return { status: res.status, data: await res.json() };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('the temporary password is long, mixed and different each time', () => {
  const seen = new Set();
  for (let i = 0; i < 200; i++) {
    const p = tempPassword();
    assert.match(p, /^[A-Za-z2-9]{4}(-[A-Za-z2-9]{4}){3}$/);
    assert.ok(/[A-Z]/.test(p) && /[a-z]/.test(p) && /[2-9]/.test(p));
    seen.add(p);
  }
  assert.equal(seen.size, 200);
});

test('no Supabase settings: a plain set-up message', async () => {
  fake();
  const r = await run(add, 'add', 'tok-owner', {}, {});
  assert.equal(r.status, 500);
  assert.match(r.data.error, /SUPABASE_SECRET_KEY/);
});

test('no token, a bad token, a stranger and a Member are all turned away', async () => {
  const f = fake();
  assert.equal((await run(add, 'add', null, {})).status, 401);
  assert.equal((await run(add, 'add', 'tok-bad', {})).status, 401);
  assert.equal((await run(add, 'add', 'tok-stranger', { full_name: 'X', email: 'x@example.com' })).status, 403);
  assert.equal((await run(add, 'add', 'tok-member', { full_name: 'X', email: 'x@example.com' })).status, 403);
  assert.equal((await run(resend, 'resend', 'tok-member', { team_id: OWNER.id })).status, 403);
  assert.ok(!f.calls.some((c) => c.method === 'POST' && c.url.pathname.startsWith('/auth/v1/admin')), 'no login was made');
});

test('an Admin adds a new person: team row, login, message; Slack is off', async () => {
  const f = fake();
  const r = await run(add, 'add', 'tok-admin', { full_name: ' Nora New ', email: 'Nora@Example.com', access: 'Member', job_title: 'Writer' });
  assert.equal(r.status, 200, JSON.stringify(r.data));
  assert.equal(r.data.email, 'nora@example.com');
  assert.equal(r.data.slack, 'off');
  const row = f.team.find((x) => x.email === 'nora@example.com');
  assert.deepEqual([row.full_name, row.access, row.status, row.can_sign_in, row.job_title], ['Nora New', 'Member', 'Active', true, 'Writer']);
  const login = f.logins.get('nora@example.com');
  assert.equal(login.meta.must_set_password, true);
  assert.ok(r.data.message.includes('Temporary password: ' + login.password));
  assert.ok(r.data.message.includes('Sign in here: https://os.example.com'));
  assert.ok(r.data.message.includes('Hi Nora,'));
  assert.ok(r.data.message.includes('Test Agency OS'));
});

test('the OS address comes from settings when it is set', async () => {
  fake({ osUrl: 'https://ops.example.com/' });
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Nora', email: 'nora@example.com' });
  assert.ok(r.data.message.includes('Sign in here: https://ops.example.com\n'));
});

test('an Admin cannot add an Owner, or change an Owner; an Owner can', async () => {
  fake();
  assert.equal((await run(add, 'add', 'tok-admin', { full_name: 'X', email: 'x@example.com', access: 'Owner' })).status, 403);
  assert.equal((await run(add, 'add', 'tok-admin', { full_name: 'O', email: OWNER.email, access: 'Member' })).status, 403);
  assert.equal((await run(resend, 'resend', 'tok-admin', { team_id: OWNER.id })).status, 403);
  assert.equal((await run(add, 'add', 'tok-owner', { full_name: 'X', email: 'x@example.com', access: 'Owner' })).status, 200);
});

test('bad input gets a plain answer', async () => {
  fake();
  assert.equal((await run(add, 'add', 'tok-owner', { full_name: '', email: 'x@example.com' })).status, 400);
  assert.equal((await run(add, 'add', 'tok-owner', { full_name: 'X', email: 'not-an-email' })).status, 400);
  assert.equal((await run(resend, 'resend', 'tok-owner', { team_id: 'x' })).status, 400);
  assert.equal((await run(resend, 'resend', 'tok-owner', { team_id: '99999999-9999-4999-8999-999999999999' })).status, 404);
});

test('an unknown access level becomes Member', async () => {
  const f = fake();
  await run(add, 'add', 'tok-owner', { full_name: 'X', email: 'x@example.com', access: 'God' });
  assert.equal(f.team.find((x) => x.email === 'x@example.com').access, 'Member');
});

test('resend resets an existing login with a new password', async () => {
  const f = fake({ logins: [MEMBER.email] });
  const r = await run(resend, 'resend', 'tok-admin', { team_id: MEMBER.id });
  assert.equal(r.status, 200, JSON.stringify(r.data));
  const login = f.logins.get(MEMBER.email);
  assert.equal(login.meta.must_set_password, true);
  assert.ok(r.data.message.includes('Temporary password: ' + login.password));
  assert.ok(f.calls.some((c) => c.method === 'PUT'), 'the existing login was reset');
});

test('resend refuses a person who cannot sign in', async () => {
  const f = fake({ logins: [GONE.email] });
  const r = await run(resend, 'resend', 'tok-owner', { team_id: GONE.id });
  assert.equal(r.status, 409);
  assert.equal(f.logins.get(GONE.email).password, undefined, 'the login was not touched');
});

test('adding someone again brings back sign-in and resets their login', async () => {
  const f = fake({ logins: [GONE.email] });
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Gus Gone', email: GONE.email, access: 'Member' });
  assert.equal(r.status, 200);
  const row = f.team.find((x) => x.email === GONE.email);
  assert.deepEqual([row.status, row.can_sign_in], ['Active', true]);
  assert.ok(f.logins.get(GONE.email).password);
});

test('with the automations set up, the message also goes to /team-invite with X-OS-Secret', async () => {
  const f = fake();
  const env = { ...ENV, MODAL_ALERTS_URL: 'https://alerts.example.com/', OS_SHARED_SECRET: 'shh' };
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Nora New', email: 'nora@example.com' }, env);
  assert.equal(r.data.slack, 'sent');
  const sent = f.calls.find((c) => c.url.origin === 'https://alerts.example.com');
  assert.equal(sent.url.pathname, '/team-invite');
  assert.equal(sent.headers['X-OS-Secret'], 'shh');
  assert.deepEqual(Object.keys(sent.body).sort(), ['email', 'message', 'name']);
  assert.equal(sent.body.message, r.data.message);
});

test('the automations address also works under its tab 3 name, OS_AUTOMATIONS_URL', async () => {
  const f = fake();
  const env = { ...ENV, OS_AUTOMATIONS_URL: 'https://alerts.example.com', OS_SHARED_SECRET: 'shh' };
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Nora', email: 'nora@example.com' }, env);
  assert.equal(r.data.slack, 'sent');
  assert.ok(f.calls.some((c) => c.url.href === 'https://alerts.example.com/team-invite'));
});

test('a Slack failure still gives the message to copy', async () => {
  fake({ slackFails: true });
  const env = { ...ENV, MODAL_ALERTS_URL: 'https://alerts.example.com', OS_SHARED_SECRET: 'shh' };
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Nora', email: 'nora@example.com' }, env);
  assert.equal(r.status, 200);
  assert.equal(r.data.slack, 'failed');
  assert.ok(r.data.message.includes('Temporary password: '));
});

test('the secret key never appears in an answer', async () => {
  fake();
  const r = await run(add, 'add', 'tok-owner', { full_name: 'Nora', email: 'nora@example.com' });
  assert.ok(!JSON.stringify(r.data).includes('test-secret'));
});

const MCP = { ...ENV, OS_AUTOMATIONS_URL: 'https://alerts.example.com/', OS_SHARED_SECRET: 'shh' };

test('Connect your AI: a Member and a stranger are turned away, and nothing reaches the automations', async () => {
  const f = fake();
  assert.equal((await run(ai, 'ai', 'tok-member', { team_id: MEMBER.id, action: 'issue' }, MCP)).status, 403);
  assert.equal((await run(ai, 'ai', 'tok-stranger', { team_id: MEMBER.id, action: 'issue' }, MCP)).status, 403);
  assert.equal((await run(ai, 'ai', null, { team_id: MEMBER.id, action: 'issue' }, MCP)).status, 401);
  assert.ok(!f.calls.some((c) => c.url.pathname === '/mcp/token'));
});

test('Connect your AI: an Admin gets the link; the call carries the secret and their own sign-in', async () => {
  const f = fake();
  const r = await run(ai, 'ai', 'tok-admin', { team_id: MEMBER.id, action: 'issue' }, MCP);
  assert.equal(r.status, 200, JSON.stringify(r.data));
  assert.deepEqual(r.data, { server: 'https://alerts.example.com/mcp/', key: 'secret-link',
    url: 'https://alerts.example.com/mcp/s/secret-link/' });
  const call = f.calls.find((c) => c.url.pathname === '/mcp/token');
  assert.equal(call.headers['X-OS-Secret'], 'shh');
  assert.equal(call.headers.Authorization, 'Bearer tok-admin');
  assert.deepEqual(call.body, { team_id: MEMBER.id, action: 'issue' });
});

test('An automations app from before link option 1 (only the url): the box still gets server and key', async () => {
  fake({ oldLink: true });
  const r = await run(ai, 'ai', 'tok-admin', { team_id: MEMBER.id, action: 'issue' }, MCP);
  assert.deepEqual(r.data, { server: 'https://alerts.example.com/mcp/', key: 'secret-link',
    url: 'https://alerts.example.com/mcp/s/secret-link/' });
  assert.deepEqual(linkParts('https://a-b--os.modal.run/mcp/s/Ab_9-x/'),
    { server: 'https://a-b--os.modal.run/mcp/', key: 'Ab_9-x', url: 'https://a-b--os.modal.run/mcp/s/Ab_9-x/' });
  assert.equal(linkParts('https://a.example.com/mcp/s/tok').server, 'https://a.example.com/mcp/');
  assert.equal(linkParts('https://a.example.com/mcp/'), null);
  assert.equal(linkParts(''), null);
  assert.equal(linkParts(undefined), null);
});

test("The box's lines are tab 5's lines, with the real server and key", async () => {
  if (!process.features.typescript) return;
  const { aiSetup, WEB_WARNING, WEB_PLANS } = await import('../src/lib/ailink.ts');
  const s = aiSetup({ server: 'https://x--os.modal.run/mcp/', key: 'K3y_-', url: 'https://x--os.modal.run/mcp/s/K3y_-/' });
  assert.deepEqual(s.map((x) => x.tool), ['Claude Code', 'Codex', 'Hermes', 'Claude on the web (claude.ai)']);
  assert.equal(s[0].text, 'claude mcp add --transport http --scope user agency-os "https://x--os.modal.run/mcp/" --header "Authorization: Bearer K3y_-"');
  assert.equal(s[1].text, '[mcp_servers.agency_os]\nurl = "https://x--os.modal.run/mcp/"\nhttp_headers = { "Authorization" = "Bearer K3y_-" }');
  assert.equal(s[2].text, 'agency_os:\n  url: "https://x--os.modal.run/mcp/"\n  headers:\n    Authorization: "Bearer K3y_-"');
  assert.equal(s[3].text, 'https://x--os.modal.run/mcp/s/K3y_-/');
  assert.equal(WEB_WARNING, "Modal's log keeps this link. Use it only if nobody else can open your Modal account.");
  assert.match(WEB_PLANS, /^Custom connectors work on the Free \(one connector at most\), Pro and Max plans\. .* use Claude Code, Codex or Hermes instead\.$/);
  /* Only the claude.ai way puts the key in an address. */
  assert.ok(s.slice(0, 3).every((x) => !x.text.includes('/mcp/s/')));
});

test('Revoke: an Admin revokes; the answer is {revoked: true}', async () => {
  const f = fake();
  const r = await run(ai, 'ai', 'tok-admin', { team_id: MEMBER.id, action: 'revoke' }, MCP);
  assert.deepEqual(r.data, { revoked: true });
  assert.equal(f.calls.find((c) => c.url.pathname === '/mcp/token').body.action, 'revoke');
});

test('Connect your AI: plain answers when it cannot work', async () => {
  fake();
  assert.equal((await run(ai, 'ai', 'tok-owner', { team_id: MEMBER.id, action: 'nope' }, MCP)).status, 400);
  assert.equal((await run(ai, 'ai', 'tok-owner', { team_id: '99999999-9999-4999-8999-999999999999', action: 'issue' }, MCP)).status, 404);
  const gone = await run(ai, 'ai', 'tok-owner', { team_id: GONE.id, action: 'issue' }, MCP);
  assert.equal(gone.status, 409);
  const off = await run(ai, 'ai', 'tok-owner', { team_id: MEMBER.id, action: 'issue' }, ENV);
  assert.equal(off.status, 409);
  assert.match(off.data.error, /tab 5/);
  fake({ mcpDown: true });
  assert.equal((await run(ai, 'ai', 'tok-owner', { team_id: MEMBER.id, action: 'issue' }, MCP)).status, 502);
  fake({ mcpError: 'Only an Owner or Admin can do that.' });
  const no = await run(ai, 'ai', 'tok-owner', { team_id: MEMBER.id, action: 'issue' }, MCP);
  assert.equal(no.status, 403);
  assert.equal(no.data.error, 'Only an Owner or Admin can do that.');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
