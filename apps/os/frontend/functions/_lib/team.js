/* The shared parts of the two Team server steps (api/team/add.js, api/team/resend.js).
 *
 * These run on Cloudflare Pages Functions, next to the OS. They hold the Supabase secret key
 * as a Cloudflare secret; the browser never sees it. This file has no onRequest export, so
 * Cloudflare makes no address for it.
 *
 * Env (Cloudflare Pages > Settings > Variables and Secrets):
 *   SUPABASE_URL          the project address
 *   SUPABASE_SECRET_KEY   the secret key (a secret, never a plain variable)
 *   OS_AUTOMATIONS_URL    optional: the automations app (tab 3). When set, the ready message is
 *                         also POSTed to <OS_AUTOMATIONS_URL>/team-invite as {email, name, message},
 *                         and the automations send it to the person as a Slack direct message.
 *                         (MODAL_ALERTS_URL is read too, as an older name for the same thing.)
 *   OS_SHARED_SECRET      sent as the X-OS-Secret header on that call. The automations turn away
 *                         any call without it.
 *
 * WHAT STOPS A STRANGER. The caller's own sign-in token is checked with Supabase, and their
 * email must be an Active team row with "can sign in" ticked and access Owner or Admin. Only an
 * Owner may add an Owner, or reset an Owner's access.
 */

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const ACCESS = ['Owner', 'Admin', 'Member'];

export function json(body, status) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

/** A short, plain answer for the person on the Team screen. */
export function refuse(status, error) { return json({ error }, status); }

function base(env) { return String(env.SUPABASE_URL || '').replace(/\/+$/, ''); }

/** A call to Supabase with the secret key. */
export function sb(env, path, opts) {
  const o = opts || {};
  const headers = {
    apikey: env.SUPABASE_SECRET_KEY,
    Authorization: 'Bearer ' + (o.token || env.SUPABASE_SECRET_KEY),
    'Content-Type': 'application/json',
  };
  if (o.prefer) headers.Prefer = o.prefer;
  return fetch(base(env) + path, {
    method: o.method || (o.body === undefined ? 'GET' : 'POST'),
    headers,
    body: o.body === undefined ? undefined : JSON.stringify(o.body),
  });
}

/** Nothing works without the two Supabase values. */
export function notSetUp(env) {
  if (env.SUPABASE_URL && env.SUPABASE_SECRET_KEY) return null;
  return refuse(500, 'The server step is not set up yet. Add SUPABASE_URL and SUPABASE_SECRET_KEY to the Cloudflare Pages project (Settings > Variables and Secrets), then deploy again.');
}

/** One team row by a filter ('email=eq.x' or 'id=eq.y'), or null. */
export async function teamRow(env, filter) {
  const res = await sb(env, '/rest/v1/team?select=id,full_name,email,access,status,can_sign_in&' + filter + '&limit=1');
  if (!res.ok) throw new Error('team lookup ' + res.status);
  const rows = await res.json();
  return rows[0] || null;
}

/** The caller's team row when they may add people, else a Response that says why not. */
export async function admin(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const token = auth.replace(/^Bearer\s+/i, '').trim();
  if (!token) return refuse(401, 'Sign in first.');
  const who = await sb(env, '/auth/v1/user', { token });
  if (!who.ok) return refuse(401, 'Your sign-in has run out. Reload the page and sign in again.');
  const user = await who.json();
  const email = String(user.email || '').toLowerCase();
  const row = email ? await teamRow(env, 'email=eq.' + encodeURIComponent(email)) : null;
  if (!row || row.status !== 'Active' || !row.can_sign_in || (row.access !== 'Owner' && row.access !== 'Admin')) {
    return refuse(403, 'Only an Owner or an Admin can add people or resend access.');
  }
  return row;
}

/** A random temporary password: 4 groups of 4, no look-alike letters, always with a capital,
 *  a small letter and a number. Longer than the 10 the sign-in settings ask for. */
export function tempPassword() {
  const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  for (;;) {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    let out = '';
    for (let i = 0; i < bytes.length && out.length < 16; i++) {
      if (bytes[i] < 224) out += abc[bytes[i] % abc.length]; // 224 = 4 x 56: no bias
    }
    if (out.length === 16 && /[A-Z]/.test(out) && /[a-z]/.test(out) && /[2-9]/.test(out)) {
      return out.match(/.{4}/g).join('-');
    }
  }
}

/** Make the person's login with this password, or give an existing login this password.
 *  Either way the login is marked "must set a password", so the first sign-in asks for their own. */
export async function setLogin(env, email, fullName, password) {
  const meta = { full_name: fullName, must_set_password: true };
  const made = await sb(env, '/auth/v1/admin/users', { body: { email, password, email_confirm: true, user_metadata: meta } });
  if (made.ok) return (await made.json()).id;
  const why = await made.text();
  if (made.status !== 422 && !/already|exists/i.test(why)) throw new Error('making the login: ' + made.status + ' ' + why.slice(0, 200));
  // The login is there already. Find its id without sending anything, then reset it.
  const link = await sb(env, '/auth/v1/admin/generate_link', { body: { type: 'magiclink', email } });
  if (!link.ok) throw new Error('finding the login: ' + link.status);
  const user = await link.json();
  const id = user.id || (user.user && user.user.id);
  if (!id) throw new Error('finding the login: no id');
  const reset = await sb(env, '/auth/v1/admin/users/' + id, { method: 'PUT', body: { password, email_confirm: true, user_metadata: meta } });
  if (!reset.ok) throw new Error('resetting the login: ' + reset.status);
  return id;
}

/** The ready message: where to sign in, the email and the temporary password. */
export async function readyMessage(env, request, person, password) {
  let agency = '';
  let osUrl = '';
  try {
    const res = await sb(env, '/rest/v1/settings?select=agency_name,os_url&limit=1');
    if (res.ok) { const s = (await res.json())[0] || {}; agency = s.agency_name || ''; osUrl = s.os_url || ''; }
  } catch (e) { /* the message still works without them */ }
  const address = (osUrl || new URL(request.url).origin).replace(/\/+$/, '');
  const first = String(person.full_name || '').trim().split(/\s+/)[0] || 'there';
  return [
    'Hi ' + first + ',',
    '',
    'You now have access to the ' + (agency ? agency + ' ' : '') + 'OS.',
    '',
    'Sign in here: ' + address,
    'Email: ' + person.email,
    'Temporary password: ' + password,
    '',
    'When you first sign in, you will choose your own password.',
  ].join('\n');
}

/** Send the message as a Slack direct message through the automations, when they are set up.
 *  'sent', 'off' (not set up) or 'failed'. A failure never stops the step: the owner still
 *  gets the message to copy. */
export async function sendToSlack(env, person, message) {
  const url = String(env.OS_AUTOMATIONS_URL || env.MODAL_ALERTS_URL || '').replace(/\/+$/, '');
  if (!url) return 'off';
  if (!env.OS_SHARED_SECRET) return 'failed';
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 8000);
  try {
    const res = await fetch(url + '/team-invite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-OS-Secret': env.OS_SHARED_SECRET },
      body: JSON.stringify({ email: person.email, name: person.full_name, message }),
      signal: stop.signal,
    });
    return res.ok ? 'sent' : 'failed';
  } catch (e) {
    return 'failed';
  } finally {
    clearTimeout(timer);
  }
}

/** Read the JSON body, or {} when there is none. */
export async function body(request) {
  try { return await request.json(); } catch (e) { return {}; }
}
