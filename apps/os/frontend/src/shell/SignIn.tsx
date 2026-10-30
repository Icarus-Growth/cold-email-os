/* The sign-in screen (email and password), and the "set your own password" screen a person
 * sees once, after they first sign in with the temporary password they were sent. */
import React, { useEffect, useRef, useState } from 'react';
import * as Auth from '../lib/auth';
import { Button } from '../ui';
import { Mark } from './Mark';

const BOX = 'w-full h-[40px] rounded-[10px] border border-line bg-card px-3 text-[14px] focus:outline-none focus:border-[var(--border-focus)] focus:ring-2 focus:ring-[var(--focus-ring)]';
const MIN = 10; // the same as minimum_password_length in apps/os/backend/supabase/config.toml

function Frame({ title, line, children, onSubmit }: { title: string; line: React.ReactNode; children: React.ReactNode; onSubmit: (e: React.FormEvent) => void }) {
  return (
    <div className="min-h-full h-full overflow-y-auto bg-ground flex flex-col items-center justify-center p-4 font-sans">
      <div className="mb-5"><Mark size={40} radius={10} /></div>
      <form noValidate onSubmit={onSubmit} className="w-full max-w-[400px] rounded-[16px] bg-card border border-line shadow-[var(--shadow-sm)] p-6 space-y-4">
        <div>
          <h1 className="font-display text-[22px] font-semibold text-ink">{title}</h1>
          <p className="text-[13.5px] text-muted mt-1">{line}</p>
        </div>
        {children}
      </form>
    </div>
  );
}

export function SignIn({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { if (first.current) first.current.focus(); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim().toLowerCase();
    if (!addr || !password) { setError('Type your email and your password.'); return; }
    setBusy(true); setError(null);
    try { await Auth.signIn(addr, password); onDone(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <Frame title="Sign in" line="Use the email and password you were sent. Ask the owner of the OS if you do not have them." onSubmit={submit}>
      <label className="block">
        <span className="block text-[12.5px] text-muted mb-1">Work email</span>
        <input ref={first} className={BOX} type="email" autoComplete="username" inputMode="email" placeholder="you@youragency.com"
          value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} aria-invalid={!!error} />
      </label>
      <label className="block">
        <span className="block text-[12.5px] text-muted mb-1">Password</span>
        <input className={BOX} type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} disabled={busy} aria-invalid={!!error} />
      </label>
      {error && <p role="alert" className="text-[13px] text-bad">{error}</p>}
      <Button type="submit" variant="primary" className="w-full" disabled={busy}>{busy ? 'One moment…' : 'Sign in'}</Button>
      <p className="text-[12px] text-faint">Forgot your password? Ask an owner or admin to press "Resend access" on your page in Team.</p>
    </Frame>
  );
}

export function SetPassword({ onDone }: { onDone: () => void }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (a.length < MIN) { setError('Use at least ' + MIN + ' characters.'); return; }
    if (a !== b) { setError('The two passwords are not the same.'); return; }
    setBusy(true); setError(null);
    try { await Auth.setPassword(a); onDone(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <Frame title="Set your own password" line={<>You signed in with a temporary password. Choose your own now: at least {MIN} characters. You will use it from now on.</>} onSubmit={submit}>
      <input type="email" autoComplete="username" value={Auth.email()} readOnly hidden />
      <label className="block">
        <span className="block text-[12.5px] text-muted mb-1">New password</span>
        <input className={BOX} type="password" autoComplete="new-password" autoFocus value={a} onChange={(e) => setA(e.target.value)} disabled={busy} />
      </label>
      <label className="block">
        <span className="block text-[12.5px] text-muted mb-1">The same password again</span>
        <input className={BOX} type="password" autoComplete="new-password" value={b} onChange={(e) => setB(e.target.value)} disabled={busy} />
      </label>
      {error && <p role="alert" className="text-[13px] text-bad">{error}</p>}
      <Button type="submit" variant="primary" className="w-full" disabled={busy}>{busy ? 'Saving…' : 'Save my password'}</Button>
      <Button variant="ghost" className="w-full" onClick={Auth.signOut}>Sign out</Button>
    </Frame>
  );
}
