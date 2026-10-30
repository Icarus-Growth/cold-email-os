import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/sora/latin-500.css';
import '@fontsource/sora/latin-600.css';
import '@fontsource/sora/latin-700.css';
import './index.css';
import * as Auth from './lib/auth';
import { CONNECTED } from './lib/config';
import { loadAll, startRefresh } from './lib/store';
import { Shell } from './shell/Shell';
import { SetPassword, SignIn } from './shell/SignIn';

type Phase = { k: 'boot' } | { k: 'signin' } | { k: 'password' } | { k: 'ready' } | { k: 'fail'; title: string; detail: React.ReactNode };

function Fail({ title, detail }: { title: string; detail: React.ReactNode }) {
  return (
    <div className="h-full bg-ground font-sans p-10 max-[720px]:p-4 overflow-y-auto">
      <h1 className="font-display text-[26px] font-semibold text-ink">{title}</h1>
      <div className="mt-3 text-[14px] text-ink2 max-w-[640px] leading-[22px]">{detail}</div>
    </div>
  );
}

const signOutLink = <a href="#" className="underline" onClick={(e) => { e.preventDefault(); Auth.signOut(); }}>sign out</a>;

function App() {
  const [phase, setPhase] = useState<Phase>({ k: 'boot' });

  async function boot() {
    try {
      const S = await loadAll();
      if (!S.me || S.me.status !== 'Active' || !S.me.can_sign_in) {
        setPhase({ k: 'fail', title: 'This login cannot see anything yet', detail: <>
          You are signed in as <code>{Auth.email()}</code>, but you are not on the team list with "Can sign in" ticked.
          Ask an owner or admin of the OS to add you or tick it on your page in Team. Then {signOutLink} and sign in again.
        </> });
        return;
      }
      setPhase({ k: 'ready' });
      startRefresh();
    } catch (err) {
      setPhase({ k: 'fail', title: 'Could not reach the database', detail: <>{String((err as Error).message || err)}<br />Check your connection, then reload the page, or {signOutLink}.</> });
    }
  }

  useEffect(() => {
    if (!CONNECTED) {
      setPhase({ k: 'fail', title: 'The OS is not connected to a database yet', detail: <>
        Put <code>SUPABASE_URL</code> and <code>SUPABASE_PUBLISHABLE_KEY</code> in the <code>.env</code> file at the top of the repo
        (or in the Cloudflare Pages build settings), then build the OS again.
      </> });
      return;
    }
    Auth.start().then((s) => { if (s === 'ready') boot(); else setPhase({ k: s }); });
  }, []);

  if (phase.k === 'boot') return <div className="os-boot">Loading…</div>;
  if (phase.k === 'signin') return <SignIn onDone={() => { setPhase({ k: Auth.mustSetPassword() ? 'password' : 'boot' }); if (!Auth.mustSetPassword()) boot(); }} />;
  if (phase.k === 'password') return <SetPassword onDone={() => { setPhase({ k: 'boot' }); boot(); }} />;
  if (phase.k === 'fail') return <Fail title={phase.title} detail={phase.detail} />;
  return <Shell />;
}

createRoot(document.getElementById('root')!).render(<App />);
