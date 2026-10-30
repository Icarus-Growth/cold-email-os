/* Sign-in: email and password, straight against Supabase. No client library.
 *
 *   1. POST /auth/v1/token?grant_type=password {email, password}  -> a session
 *   2. every request after that sends the access token; the team-only rules in the
 *      database (0005_access.sql) decide what it can read and write
 *   3. a login made by "Add team member" or "Resend access" carries
 *      user_metadata.must_set_password = true: the person sets their own password
 *      (PUT /auth/v1/user) before they see anything
 *
 * The access token lasts an hour. It is refreshed a couple of minutes before it runs out,
 * and before any request that finds it nearly spent. The session is kept in localStorage.
 */
import { CONFIG } from './config';

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  email: string;
  must_set_password: boolean;
}

const KEY = 'os-session';
const EARLY_S = 120; // refresh this many seconds before expiry

let session: Session | null = null;
let inflight: Promise<void> | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;

const now = () => Math.floor(Date.now() / 1000);

function save(s: Session | null) {
  session = s;
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch { /* storage blocked: session lives for this tab only */ }
  schedule();
}

function restore() {
  try { session = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { session = null; }
}

interface User { email?: string; user_metadata?: Record<string, unknown> }
interface TokenResponse {
  access_token: string; refresh_token: string; expires_at?: number; expires_in?: number; user?: User;
}

function fromResponse(d: TokenResponse): Session {
  const meta = (d.user && d.user.user_metadata) || {};
  return {
    access_token: d.access_token,
    refresh_token: d.refresh_token,
    expires_at: d.expires_at || now() + (d.expires_in || 3600),
    email: ((d.user && d.user.email) || (session && session.email) || '').toLowerCase(),
    must_set_password: meta.must_set_password === true,
  };
}

export class HttpError extends Error {
  status: number;
  constructor(msg: string, status: number) { super(msg); this.status = status; }
}

async function authFetch(path: string, body: unknown, method = 'POST', bearer?: string): Promise<any> {
  const headers: Record<string, string> = { apikey: CONFIG.SUPABASE_PUBLISHABLE_KEY, 'Content-Type': 'application/json' };
  if (bearer) headers.Authorization = 'Bearer ' + bearer;
  const res = await fetch(CONFIG.SUPABASE_URL + '/auth/v1/' + path, { method, headers, body: JSON.stringify(body) });
  const d = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new HttpError(d.msg || d.error_description || d.message || 'HTTP ' + res.status, res.status);
  }
  return d;
}

function refresh(): Promise<void> {
  if (inflight) return inflight;
  const s = session;
  if (!s) return Promise.reject(new Error('signed out'));
  inflight = authFetch('token?grant_type=refresh_token', { refresh_token: s.refresh_token })
    .then((d: TokenResponse) => { save(fromResponse(d)); })
    .catch((err: HttpError) => {
      // A 4xx means the refresh token is dead (signed out elsewhere, revoked).
      // Anything else is the network: keep the session and try again later.
      if (err.status && err.status < 500) expired();
      throw err;
    })
    .finally(() => { inflight = null; });
  return inflight;
}

function schedule() {
  clearTimeout(timer);
  if (!session) return;
  const wait = Math.max(5, session.expires_at - now() - EARLY_S);
  timer = setTimeout(() => { refresh().catch(() => {}); }, wait * 1000);
}

/** Resolve once the access token has at least two minutes left. */
export function fresh(): Promise<void> {
  if (!session) return Promise.reject(new Error('signed out'));
  if (session.expires_at - now() > EARLY_S) return Promise.resolve();
  return refresh();
}

/** The session is gone: back to sign-in. */
export function expired() {
  save(null);
  location.reload();
}

/** Sign out here and at Supabase, then reload to the sign-in screen. */
export function signOut() {
  const t = session && session.access_token;
  save(null);
  const done = () => location.reload();
  if (!t) { done(); return; }
  fetch(CONFIG.SUPABASE_URL + '/auth/v1/logout', {
    method: 'POST',
    headers: { apikey: CONFIG.SUPABASE_PUBLISHABLE_KEY, Authorization: 'Bearer ' + t },
  }).then(done, done);
}

/** The bearer token for the database (the publishable key when signed out). */
export function token(): string { return session ? session.access_token : CONFIG.SUPABASE_PUBLISHABLE_KEY; }
/** The signed-in email ('' when signed out). */
export function email(): string { return session ? session.email : ''; }
/** True until a person who signed in with a temporary password sets their own. */
export function mustSetPassword(): boolean { return !!(session && session.must_set_password); }

/** Boot: 'ready' when a session exists, 'signin' when the sign-in screen must show,
 *  'password' when the person must set their own password first. */
export async function start(): Promise<'ready' | 'signin' | 'password'> {
  restore();
  if (!session || !session.refresh_token) return 'signin';
  schedule();
  try { await fresh(); } catch {
    // Network trouble on a stored session: try the app anyway; requests will
    // refresh again. A dead refresh token already reloaded the page.
    if (!session) return 'signin';
  }
  return mustSetPassword() ? 'password' : 'ready';
}

/** Sign in with an email and a password. */
export async function signIn(address: string, password: string): Promise<void> {
  try {
    save(fromResponse(await authFetch('token?grant_type=password', { email: address, password })));
  } catch (e) {
    const err = e as HttpError;
    if (err.status === 400) throw new Error('That email and password do not match. Check both and try again.');
    throw new Error('Could not sign you in: ' + err.message);
  }
}

/** Set the signed-in person's own password, and clear the "must set a password" mark. */
export async function setPassword(password: string): Promise<void> {
  await fresh();
  const s = session!;
  try {
    const user: User = await authFetch('user', { password, data: { must_set_password: false } }, 'PUT', s.access_token);
    const meta = user.user_metadata || {};
    save({ ...s, must_set_password: meta.must_set_password === true });
  } catch (e) {
    const err = e as HttpError;
    if (/reauth/i.test(err.message)) throw new Error('Please sign out, sign in again, then set your password.');
    throw new Error('Could not set your password: ' + err.message);
  }
}
