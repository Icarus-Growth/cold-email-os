/* Team: the list of people, one page per person, "Add team member", "Resend access", and the
 * OS settings (Owners and Admins only).
 *
 * Adding a person is one button: the server step (functions/api/team/add.js) puts them on the
 * team with "can sign in" ticked, makes their login with a temporary password and gives back a
 * ready message to copy. On their first sign-in they set their own password.
 * To take access away, untick "Can sign in": they keep their login but see nothing. */
import { useState } from 'react';
import { Bot, Copy, KeyRound, Unplug, UserPlus } from 'lucide-react';
import { TEAM_DEV, TEAM_SECTIONS, SETTINGS_FIELDS } from '../../core.config';
import { BOARDS, isOpen } from '../../lib/schema';
import { Button, ChoicePill, DataTable, Modal, Notice, RecordPage, Sections, StagePill, Tag, type SectionSpec } from '../../ui';
import { refreshAll, useData, type Data, type Row } from '../../lib/store';
import { navigate, openCard } from '../../lib/router';
import { confirm, createOpen, filterValue, screenFilters, setScreenFilter, toast } from '../../lib/ui';
import { addMember, connectAI, resendAccess, revokeAI, type AccessResult, type AILinkParts } from '../../lib/team';
import { aiSetup, WEB_PLANS, WEB_WARNING } from '../../lib/ailink';
import { dateTime, dueLine } from '../../lib/format';
import { devSection, fieldSpec, sectionSpec } from '../records/fields';
import { copyText } from '../records/CardPanel';

/** Every open card a person must act on, on every board. */
function openCardsOf(S: Data, teamId: string) {
  return BOARDS.flatMap((b) => S.rows(b.table).filter((r) => r.assignee_id === teamId && isOpen(b, r)).map((r) => ({ def: b, row: r })));
}

/* ---------- the ready message, shown once ------------------------------------- */

function Ready({ result, onClose }: { result: AccessResult; onClose: () => void }) {
  return (
    <Modal title="Send this to them" onClose={onClose} footer={<>
      <Button variant="primary" icon={Copy} onClick={() => copyText(result.message, 'Message copied.')}>Copy the message</Button>
      <Button onClick={onClose}>Done</Button>
    </>}>
      <div className="space-y-3" data-ready>
        <p className="text-[13px] text-ink2">
          This is the only time the temporary password is shown. Copy the message and send it to {result.email}.
          On their first sign-in they set their own password.
        </p>
        <pre className="whitespace-pre-wrap break-words rounded-[10px] bg-ground border border-line p-3 text-[13px] text-ink font-sans" data-message>{result.message}</pre>
        <p className="text-[12.5px] text-muted">
          {result.slack === 'sent' ? 'It was also sent to them as a Slack direct message.'
            : result.slack === 'failed' ? 'The Slack message did not go out. Send this one yourself.'
            : 'Slack is not set up yet, so send this one yourself.'}
        </p>
      </div>
    </Modal>
  );
}

/* ---------- "Add team member" --------------------------------------------------- */

export function AddMember({ onClose }: { onClose: () => void }) {
  const S = useData();
  const [form, setForm] = useState({ full_name: '', email: '', access: 'Member', job_title: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AccessResult | null>(null);
  if (result) return <Ready result={result} onClose={onClose} />;
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const ok = form.full_name.trim() && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim());
  const roles = S.me && S.me.access === 'Owner' ? ['Member', 'Admin', 'Owner'] : ['Member', 'Admin'];
  async function submit() {
    setBusy(true); setError(null);
    try {
      const r = await addMember({ ...form, full_name: form.full_name.trim(), email: form.email.trim().toLowerCase() });
      setResult(r);
      refreshAll();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const box = 'w-full h-[36px] rounded-[10px] border border-line bg-card px-3 text-[13px] focus:outline-none focus:border-[var(--border-focus)]';
  return (
    <Modal title="Add team member" onClose={onClose} footer={<>
      <Button variant="primary" icon={UserPlus} disabled={!ok || busy} onClick={submit}>{busy ? 'Adding…' : 'Add them'}</Button>
      <Button onClick={onClose}>Cancel</Button>
    </>}>
      <form className="space-y-3" data-add-member onSubmit={(e) => { e.preventDefault(); if (ok && !busy) submit(); }}>
        <label className="block"><span className="block text-[12.5px] text-muted mb-1">Name</span>
          <input className={box} value={form.full_name} onChange={(e) => set('full_name', e.target.value)} autoFocus /></label>
        <label className="block"><span className="block text-[12.5px] text-muted mb-1">Email (they sign in with it)</span>
          <input className={box} type="email" value={form.email} onChange={(e) => set('email', e.target.value)} /></label>
        <label className="block"><span className="block text-[12.5px] text-muted mb-1">Job title (optional)</span>
          <input className={box} value={form.job_title} onChange={(e) => set('job_title', e.target.value)} /></label>
        <label className="block"><span className="block text-[12.5px] text-muted mb-1">Access</span>
          <select className={box} value={form.access} onChange={(e) => set('access', e.target.value)}>
            {roles.map((r) => <option key={r} value={r}>{r}{r === 'Member' ? ' (cannot add people)' : ' (can add people)'}</option>)}
          </select></label>
        {error && <p role="alert" className="text-[13px] text-bad">{error}</p>}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}

/* ---------- the list ------------------------------------------------------------ */

export function TeamTable() {
  const S = useData();
  const f = screenFilters.use();
  const status = filterValue(f, 'team:status', 'Active');
  const rows = S.rows('team').filter((t) => status === 'All' || t.status === status);
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap" data-filters>
          <ChoicePill label="Status" value={status} options={['Active', 'Inactive', 'All']} onChange={(v) => setScreenFilter('team:status', v)} />
          {!S.isAdmin && <span className="text-[12.5px] text-muted">Only an Owner or an Admin can add people.</span>}
        </div>
        <DataTable view="team" rows={rows} defaults={['full_name', 'job_title', 'access', 'can_sign_in', 'open', 'capacity']}
          hidden={['is_example', 'id']}
          cols={{
            full_name: { label: 'Name', w: 220, cell: (r) => ({ node: <span className="flex items-center gap-2 min-w-0"><span className="truncate font-medium text-ink">{r.full_name}</span>{r.is_example && <Tag>Example</Tag>}</span> }) },
            job_title: { label: 'Job title', w: 170, cell: (r) => ({ t: r.job_title || '—' }) },
            access: { label: 'Access', w: 100, cell: (r) => ({ t: r.access }) },
            can_sign_in: { label: 'Can sign in', w: 110, cell: (r) => ({ t: r.can_sign_in ? 'Yes' : 'No', tone: r.can_sign_in ? null : 'mute' }) },
            open: { label: 'Open cards', w: 110, align: 'right', cell: (r) => { const n = openCardsOf(S, r.id).length; return { t: String(n), tone: n > r.capacity ? 'bad' : null }; } },
            capacity: { label: 'Can hold', w: 100, align: 'right', cell: (r) => ({ t: String(r.capacity) }) },
            email: { label: 'Email', w: 220, cell: (r) => ({ t: r.email }) },
          }}
          rowTone={(r) => (openCardsOf(S, r.id).length > r.capacity ? 'bad' : null)}
          onRowClick={(r) => navigate({ screen: 'member', id: r.id })} empty="Nobody here." />
      </div>
      {S.isAdmin && <Settings />}
    </div>
  );
}

/** The one settings row: the agency name, the addresses and the dashboard's numbers. */
function Settings() {
  const S = useData();
  const row = S.settings;
  if (!row || row.id === undefined) return null;
  return (
    <div className="max-w-[920px] rounded-[14px] bg-card border border-line shadow-[var(--shadow-sm)] px-6 py-5 max-[520px]:px-4" data-settings>
      <Sections sections={[{ title: 'OS settings', desc: 'For the owner and admins. Each field saves when you click away.', fold: true, closed: true, foldKey: 'settings',
        fields: SETTINGS_FIELDS.map((fd) => fieldSpec(S, 'settings', row, fd)) }]} />
    </div>
  );
}

/* ---------- one person ------------------------------------------------------------ */

function Resend({ person }: { person: Row }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AccessResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button size="sm" icon={KeyRound} disabled={busy || !person.can_sign_in}
        title={person.can_sign_in ? 'Make a new temporary password and a new message' : 'Tick "Can sign in" first'}
        onClick={async () => {
          setBusy(true); setError(null);
          try { setResult(await resendAccess(person.id)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
        }}>{busy ? 'Working…' : 'Resend access'}</Button>
      {error && <span role="alert" className="text-[12.5px] text-bad">{error}</span>}
      {result && <Ready result={result} onClose={() => setResult(null)} />}
    </>
  );
}

/* ---------- the AI connector link (tab 5), shown once ---------------------------- */

function CopyRow({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex items-start gap-2">
      <pre className="flex-1 min-w-0 whitespace-pre-wrap break-all rounded-[10px] bg-ground border border-line px-3 py-2 text-[12.5px] leading-[18px] text-ink font-mono" data-copy>{text}</pre>
      <Button size="sm" icon={Copy} aria-label={'Copy ' + label} onClick={() => copyText(text, 'Copied ' + label + '.')}>Copy</Button>
    </div>
  );
}

/** The key, shown once, as the lines each AI tool takes (tab 5, Step 4). */
function AILink({ person, link, onClose }: { person: Row; link: AILinkParts; onClose: () => void }) {
  return (
    <Modal wide title={'AI key for ' + person.full_name} onClose={onClose} footer={<Button onClick={onClose}>Done</Button>}>
      <div className="space-y-4" data-ai-link>
        <p className="text-[13px] text-ink2">
          This is the only time the key is shown. Copy the lines for {person.full_name}'s AI now and send them to
          {' ' + person.full_name} directly, never in a shared channel or a document.
        </p>
        <section className="space-y-1.5" data-basics>
          <h3 className="text-[13.5px] font-semibold text-ink">Server address (not secret)</h3>
          <CopyRow label="the server address" text={link.server} />
          <h3 className="text-[13.5px] font-semibold text-ink pt-1">Key</h3>
          <CopyRow label="the key" text={link.key} />
          <p className="text-[12.5px] text-muted">Keep the key (and the link for Claude on the web, if used) in a password manager.</p>
        </section>
        {aiSetup(link).map((s) => (
          <section key={s.tool} className="space-y-1.5 border-t border-line2 pt-3" data-tool={s.tool}>
            <h3 className="text-[13.5px] font-semibold text-ink">{s.tool}</h3>
            <p className="text-[12.5px] text-muted">{s.where}</p>
            <CopyRow label={'the lines for ' + s.tool} text={s.text} />
            {link.url === s.text && <>
              <p className="text-[12.5px] text-[var(--warn)]" data-web-warning>{WEB_WARNING}</p>
              <p className="text-[12px] text-muted" data-web-plans>{WEB_PLANS}</p>
            </>}
          </section>
        ))}
        <p className="text-[12.5px] text-bad font-medium">
          The key and the link for Claude on the web work like a password. Anyone who has one can read and change the
          OS as {person.full_name}, with their access. If one leaks, press "Revoke".
        </p>
      </div>
    </Modal>
  );
}

/** "Connect your AI" and "Revoke": for an Owner or Admin, on each person's page. */
function ConnectAI({ person }: { person: Row }) {
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<AILinkParts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const issue = async () => {
    setBusy(true); setError(null);
    try { setLink(await connectAI(person.id)); refreshAll(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const revoke = () => confirm({
    title: 'Revoke ' + person.full_name + "'s AI key?", verb: 'Revoke the key',
    body: 'Their AI stops working with the OS within a minute. Their sign-in to the OS does not change. An Owner or Admin can give them a new key at any time.',
    run: async () => {
      setBusy(true); setError(null);
      try { await revokeAI(person.id); toast('Revoked. The old key and link no longer work.', 'good'); refreshAll(); }
      catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    },
  });
  return (
    <div className="space-y-2" data-connect-ai>
      <p className="text-[12.5px] text-muted">
        {person.mcp_last_seen_at ? 'Their AI last used the OS ' + dateTime(person.mcp_last_seen_at) + '.' : 'No AI has used a key for them yet.'}
        {' '}A new key replaces the old one.
      </p>
      <div className="flex items-center gap-2 flex-wrap">
        <Button size="sm" icon={Bot} disabled={busy || !person.can_sign_in}
          title={person.can_sign_in ? 'Make a private key for their AI' : 'Tick "Can sign in" first'}
          onClick={issue}>{busy ? 'Working…' : 'Connect your AI'}</Button>
        <Button size="sm" variant="danger" icon={Unplug} disabled={busy} onClick={revoke}>Revoke</Button>
        {error && <span role="alert" className="text-[12.5px] text-bad">{error}</span>}
      </div>
      {link && <AILink person={person} link={link} onClose={() => setLink(null)} />}
    </div>
  );
}

/** The fields a Member may change on their own row. Everything else is for an Owner or Admin
 *  (the database refuses the rest: migration 0009). */
const OWN_FIELDS = ['full_name', 'job_title', 'phone', 'slack_user_id'];

export function MemberPage({ id }: { id: string }) {
  const S = useData();
  const p = S.teamById[id];
  if (!p) return <Notice title="This person is not here.">They may have been removed, or the link is wrong.</Notice>;
  const cards = openCardsOf(S, id);
  const self = S.me && S.me.id === id;
  // The database lets an Owner or Admin change anyone, and a Member only their own name fields.
  const canEdit = S.isAdmin ? true : self ? (k: string) => OWN_FIELDS.indexOf(k) > -1 : false;
  const sections: Array<SectionSpec | null> = [
    sectionSpec(S, 'team', p, TEAM_SECTIONS[0], { canEdit }),
    sectionSpec(S, 'team', p, TEAM_SECTIONS[1], { canEdit: S.isAdmin && !self }),
    { title: 'Open cards', desc: cards.length + ' open, can hold ' + p.capacity + '. Click one to open it.',
      children: cards.length ? (
        <div className="rounded-[10px] border border-line divide-y divide-[var(--border-secondary)]" data-member-cards>
          {cards.map(({ def, row }) => {
            const due = row.due_date ? dueLine(row.due_date) : null;
            return (
              <button key={def.table + row.id} type="button" onClick={() => openCard(def.table, row.id)}
                className="w-full grid grid-cols-[1fr_auto] max-[520px]:grid-cols-1 gap-x-3 gap-y-1 items-center text-left px-3 py-2 hover:bg-ground">
                <span className="min-w-0 truncate text-[13px]"><span className="font-medium text-ink">{row[def.nameKey]}</span>
                  <span className="text-muted"> · {def.label} · {S.clientName(row.client_id)}</span></span>
                <span className="flex items-center gap-2 text-[12px]"><StagePill stage={row[def.stageKey]} />
                  {due && <span className={due.tone === 'bad' ? 'text-bad' : due.tone === 'warn' ? 'text-warn' : 'text-muted'}>{due.text}</span>}</span>
              </button>
            );
          })}
        </div>
      ) : <div className="text-[12.5px] text-faint">Nothing open.</div> },
    sectionSpec(S, 'team', p, TEAM_SECTIONS[2], { canEdit }),
    S.isAdmin ? { title: 'AI connector', desc: 'A private key that lets their own AI work on their cards. For Owners and Admins.',
                  children: <ConnectAI person={p} /> } : null,
    devSection(S, 'team', p, TEAM_DEV, canEdit),
  ];
  return (
    <RecordPage
      badge={<span className="flex items-center gap-2"><Tag tone={p.can_sign_in ? 'good' : 'grey'}>{p.can_sign_in ? 'Can sign in' : 'Cannot sign in'}</Tag><Tag>{p.access}</Tag>{p.is_example && <Tag>Example</Tag>}</span>}
      sub={p.email}
      actions={S.isAdmin && !self ? <Resend person={p} /> : null}
      sections={sections} />
  );
}

/** The header button on the Team screen. */
export function openAddMember() { createOpen.set({ table: 'team' }); }
