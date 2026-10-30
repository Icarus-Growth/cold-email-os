/* Clients: the list, and one page per client.
 *
 * The client page is sections that open and close. Every field can be edited and saves when
 * you click away. The client's cards on every board, calls, forms and weekly numbers are on
 * the same page. The ids sit in a closed "For developers" section at the bottom. */
import { Archive, ArchiveRestore, Copy, Plus, Trash2 } from 'lucide-react';
import type { FieldDef, RecordDef } from '../../config';
import { AGENCY, BOARDS, LISTS, isOpen } from '../../lib/schema';
import { CLIENT_BASIC, CLIENT_DEV, CLIENT_NOTES, CLIENT_ONBOARDING, CALL_FIELDS } from '../../core.config';
import { Button, ChoicePill, DataTable, Dot, Notice, RecordPage, StagePill, Tag, type SectionSpec } from '../../ui';
import { archiveClient, isArchived, remove, restoreClient, useData, useQuery, type Data, type Row } from '../../lib/store';
import { inApp, navigate, openCard } from '../../lib/router';
import { confirm, createOpen, filterValue, screenFilters, setScreenFilter, toast } from '../../lib/ui';
import { ago, dateLong, dateTime, dueLine } from '../../lib/format';
import { clientActions } from './actions';
import { devSection, extraFields, fieldSpec, keysOf, sectionSpec, showNumber, showValue } from '../records/fields';
import { copyText } from '../records/CardPanel';

/** The client's sections, in page order (the agency's own sections sit after Onboarding). */
export const CLIENT_SECTIONS = [CLIENT_BASIC, CLIENT_ONBOARDING, ...AGENCY.clientSections, CLIENT_NOTES];
const ALL_FIELDS: FieldDef[] = CLIENT_SECTIONS.flatMap((s) => s.fields);

/* ---------- the list ------------------------------------------------------------ */

export function ClientsTable() {
  const S = useData();
  const f = screenFilters.use();
  const status = filterValue(f, 'clients:status', 'Active');
  const archived = filterValue(f, 'clients:archived', 'Hidden');
  const rows = (archived === 'Shown' ? S.allRows('clients') : S.rows('clients')).filter((c) => status === 'All' || c.status === status);
  const openCards = (id: string) => BOARDS.reduce((n, b) => n + S.rows(b.table).filter((r) => r.client_id === id && isOpen(b, r)).length, 0);
  const roleFields = AGENCY.clientSections.flatMap((s) => s.fields).filter((x) => x.type === 'person');
  const roleCols: Record<string, { label: string; w: number; cell: (r: Row) => { t: string } }> = {};
  roleFields.forEach((x) => { roleCols[x.key] = { label: x.label, w: 160, cell: (r) => ({ t: S.teamName(r[x.key]) || '—' }) }; });
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap" data-filters>
        <ChoicePill label="Status" value={status} options={['Active', 'Paused', 'Ended', 'All']} onChange={(v) => setScreenFilter('clients:status', v)} />
        <ChoicePill label="Archived" value={archived} options={['Hidden', 'Shown']} onChange={(v) => setScreenFilter('clients:archived', v)} />
      </div>
      <DataTable view="clients" rows={rows} defaults={['client_name', 'onboarding_stage', 'account_manager_id', 'open', 'start_date']}
        hidden={['form_code', 'is_example', 'id']}
        cols={{
          client_name: { label: 'Client', w: 240, cell: (r) => ({ node: <span className="flex items-center gap-2 min-w-0"><Dot colour={S.clientColour(r.id)} size={8} />
            <span className="truncate font-medium text-ink">{r.client_name}</span>{r.is_example && <Tag>Example</Tag>}{isArchived(r) && <Tag>Archived</Tag>}</span> }) },
          onboarding_stage: { label: 'Onboarding', w: 190, cell: (r) => ({ node: <StagePill stage={r.onboarding_stage} /> }) },
          status: { label: 'Status', w: 100, cell: (r) => ({ t: r.status }) },
          open: { label: 'Open cards', w: 110, align: 'right', cell: (r) => ({ t: String(openCards(r.id)) }) },
          start_date: { label: 'Start date', w: 130, cell: (r) => ({ t: r.start_date ? dateLong(r.start_date + 'T12:00:00') : '—' }) },
          contact_name: { label: 'Main contact', w: 160, cell: (r) => ({ t: r.contact_name || '—' }) },
          ...roleCols,
        }}
        onRowClick={(r) => navigate({ screen: 'client', id: r.id })}
        empty={status === 'All' ? 'No clients yet. Press "New client" to add one.' : 'No ' + status.toLowerCase() + ' clients.'} />
    </div>
  );
}

/* ---------- the page ------------------------------------------------------------ */

/** The client's form link: <form address>/form/<code>?email=&company_name=. */
export function formLink(S: Data, c: Row): string | null {
  const base = String(S.settings.onboarding_url || '').trim().replace(/\/+$/, '');
  if (!base || !c.form_code) return null;
  const qs = new URLSearchParams();
  if (c.contact_email) qs.set('email', c.contact_email);
  if (c.client_name) qs.set('company_name', c.client_name);
  const q = qs.toString();
  return base + '/form/' + encodeURIComponent(c.form_code) + (q ? '?' + q : '');
}

/** The client's cards on one board (or list): a small table, newest first. An archived
 *  client's page shows the cards its archive hid, too. */
function Work({ S, def, client }: { S: Data; def: RecordDef; client: Row }) {
  const rows = (isArchived(client) ? S.allRows(def.table) : S.rows(def.table)).filter((r) => r.client_id === client.id);
  const open = rows.filter((r) => isOpen(def, r));
  return (
    <div className="space-y-2" data-work={def.table}>
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-ink">{def.label}</span>
        <span className="text-[12px] text-muted">{open.length} open · {rows.length} in all</span>
        <Button size="sm" icon={Plus} className="ml-auto" onClick={() => createOpen.set({ table: def.table, defaults: { client_id: client.id } })}>New {def.item}</Button>
      </div>
      {rows.length ? (
        <div className="rounded-[10px] border border-line divide-y divide-[var(--border-secondary)]">
          {rows.slice().sort((a, b) => Number(isOpen(def, b)) - Number(isOpen(def, a))).map((r) => {
            const due = r.due_date ? dueLine(r.due_date) : null;
            return (
              <button key={r.id} type="button" onClick={() => openCard(def.table, r.id)} data-work-row={r.id}
                className="w-full grid grid-cols-[1fr_auto] max-[520px]:grid-cols-1 gap-x-3 gap-y-1 items-center text-left px-3 py-2 hover:bg-ground">
                <span className="min-w-0 truncate text-[13px] font-medium text-ink">{r[def.nameKey] || 'Untitled'}{isArchived(r) && <span className="text-muted font-normal"> · archived</span>}</span>
                <span className="flex items-center gap-2 text-[12px] text-muted">
                  <StagePill stage={r[def.stageKey]} />
                  <span>{S.teamName(r.assignee_id) || 'Nobody'}</span>
                  {due && isOpen(def, r) && <span className={due.tone === 'bad' ? 'text-bad' : due.tone === 'warn' ? 'text-warn' : ''}>{due.text}</span>}
                </span>
              </button>
            );
          })}
        </div>
      ) : <div className="text-[12.5px] text-faint">None yet.</div>}
    </div>
  );
}

function Calls({ client }: { client: Row }) {
  const S = useData();
  const q = useQuery({ key: 'calls:' + client.id, table: 'calls', opts: { filter: 'client_id=eq.' + client.id, order: 'call_at.desc' } });
  const rows = q.rows || [];
  return (
    <div className="space-y-2" data-calls>
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-muted">{rows.length} {rows.length === 1 ? 'call' : 'calls'}</span>
        <Button size="sm" icon={Plus} className="ml-auto" onClick={() => createOpen.set({ table: 'calls', defaults: { client_id: client.id } })}>Add a call</Button>
      </div>
      {rows.map((c) => (
        <details key={c.id} className="rounded-[10px] border border-line px-3 py-2 group" data-call={c.id}>
          <summary className="cursor-pointer flex items-center gap-2 text-[13px]">
            <span className="font-medium text-ink truncate">{c.title}</span>
            <Tag>{c.call_type}</Tag>
            <span className="text-muted text-[12px] ml-auto shrink-0">{dateTime(c.call_at)}</span>
          </summary>
          <div className="mt-2.5 space-y-1.5">
            {CALL_FIELDS.map((fd) => { const spec = fieldSpec(S, 'calls', c, fd); return <CallField key={fd.key} spec={spec} />; })}
            <div className="pt-1">
              <Button size="sm" variant="danger" icon={Trash2} onClick={() => confirm({ title: 'Delete this call?', body: '"' + c.title + '" is deleted for everyone.', verb: 'Delete',
                run: () => { remove('calls', c.id).catch(() => {}); } })}>Delete the call</Button>
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}
function CallField({ spec }: { spec: ReturnType<typeof fieldSpec> }) {
  return (
    <div className="grid grid-cols-[minmax(96px,28%)_1fr] gap-3 items-start text-[13px] max-[520px]:grid-cols-1 max-[520px]:gap-1">
      <div className="pt-[5px] text-muted text-[12.5px]">{spec.k}</div>
      <div className="min-w-0">{spec.node !== undefined ? spec.node : <span className="text-ink">{spec.v}</span>}</div>
    </div>
  );
}

function Forms({ client }: { client: Row }) {
  const q = useQuery({ key: 'forms:' + client.id, table: 'onboarding_forms', opts: { filter: 'client_id=eq.' + client.id, order: 'submitted_at.desc' } });
  const rows = q.rows || [];
  if (!rows.length) return <div className="text-[12.5px] text-faint">No form submitted yet.</div>;
  return (
    <div className="rounded-[10px] border border-line divide-y divide-[var(--border-secondary)]">
      {rows.map((r) => {
        const to = '/forms/' + encodeURIComponent(r.id);
        return (
          <a key={r.id} href={to} onClick={(e) => inApp(e, to)} className="flex items-center gap-2 px-3 py-2 text-[13px] no-underline hover:bg-ground">
            <span className="font-medium text-ink">{r.submitted_by_name || r.submitted_by_email || 'Someone'}</span>
            <span className="text-muted ml-auto text-[12px]">{dateTime(r.submitted_at)}</span>
          </a>
        );
      })}
    </div>
  );
}

function Numbers({ client }: { client: Row }) {
  const q = useQuery({ key: 'weekly:' + client.id, table: 'weekly_metrics', opts: { filter: 'client_id=eq.' + client.id, order: 'week_start.desc', limit: 12 } });
  if (q.missing) return <div className="text-[12.5px] text-faint">The numbers table is not in the database yet.</div>;
  const rows = (q.rows || []).slice(0, 12);
  if (!rows.length) return <div className="text-[12.5px] text-faint">No numbers yet. They fill in once you connect your tools.</div>;
  return (
    <div className="overflow-x-auto rounded-[10px] border border-line">
      <table className="w-full text-[12.5px] tnum">
        <thead className="bg-ground text-muted"><tr>
          <th className="text-left font-medium px-3 py-2">Week of</th>
          {AGENCY.metrics.map((m) => <th key={m.key} className="text-right font-medium px-3 py-2 whitespace-nowrap">{m.label}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-line2">
              <td className="px-3 py-1.5 whitespace-nowrap">{dateLong(r.week_start + 'T12:00:00')}</td>
              {AGENCY.metrics.map((m) => (
                <td key={m.key} className="px-3 py-1.5 text-right whitespace-nowrap">
                  {m.format === 'url' && r[m.key] ? <a href={r[m.key]} target="_blank" rel="noopener noreferrer" className="underline">Open</a> : showNumber(r[m.key], m.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What "Archive client" hides, in plain words, with the number of cards it takes. */
function archiveText(S: Data, c: Row): string {
  const n = BOARDS.concat(LISTS).reduce((sum, b) => sum + S.rows(b.table).filter((r) => r.client_id === c.id).length, 0);
  return 'This hides the client and ' + (n === 1 ? 'its 1 card' : 'its ' + n + ' cards') + ' from the boards, the lists, '
    + 'the dashboard, the Slack alerts and the daily summary. Nothing is deleted. "Restore" on this page brings them all back. '
    + 'To see archived clients, set "Archived" to "Shown" on the Clients screen.';
}

export function ClientPage({ id }: { id: string }) {
  const S = useData();
  const c = S.clientById[id];
  if (!c) return <Notice title="This client is not here.">It may have been deleted, or the link is wrong.</Notice>;
  const link = formLink(S, c);
  const shown = keysOf(ALL_FIELDS).concat(CLIENT_DEV.map((f) => f.key));
  const extras = extraFields(c, shown);
  const fold = (title: string) => ({ fold: true, foldKey: 'client:' + title });
  const onboarding = sectionSpec(S, 'clients', c, CLIENT_ONBOARDING, fold(CLIENT_ONBOARDING.title));
  onboarding.fields = [
    ...(onboarding.fields || []),
    { k: 'Form link', desc: 'One link per client. Two people at the client can fill it together.',
      node: link
        ? <div className="flex items-center gap-2 min-w-0"><span className="truncate text-[12.5px] text-ink2">{link}</span>
            <Button size="sm" icon={Copy} className="shrink-0" onClick={() => copyText(link, 'Form link copied.')}>Copy form link</Button></div>
        : <span className="text-[12.5px] text-muted">Add the form address on the Team screen (OS settings) to get this client's link.</span> },
  ];
  const sections: Array<SectionSpec | null> = [
    sectionSpec(S, 'clients', c, CLIENT_BASIC, fold(CLIENT_BASIC.title)),
    onboarding,
    ...AGENCY.clientSections.map((s) => sectionSpec(S, 'clients', c, s, fold(s.title))),
    { title: 'Work', desc: "The client's cards on every board. Click one to open it.", ...fold('Work'),
      children: <div className="space-y-4">{BOARDS.concat(LISTS).map((b) => <Work key={b.table} S={S} def={b} client={c} />)}</div> },
    { title: 'Calls', desc: 'Sales, onboarding and check-in calls, newest first.', ...fold('Calls'), children: <Calls client={c} /> },
    { title: 'Onboarding forms', desc: 'What the client sent through the form.', ...fold('Onboarding forms'), children: <Forms client={c} /> },
    { title: 'Weekly numbers', desc: 'The last 12 weeks.', ...fold('Weekly numbers'), children: <Numbers client={c} /> },
    sectionSpec(S, 'clients', c, CLIENT_NOTES, fold(CLIENT_NOTES.title)),
    extras.length ? sectionSpec(S, 'clients', c, { title: 'More fields', desc: 'Columns the client table has that the screens do not name yet.', fields: extras }, fold('More fields')) : null,
    devSection(S, 'clients', c, CLIENT_DEV),
  ];
  const acts = clientActions(S.isAdmin, isArchived(c));
  return (
    <RecordPage
      badge={<span className="flex items-center gap-2"><Dot colour={S.clientColour(c.id)} size={10} /><StagePill stage={c.onboarding_stage} />{c.is_example && <Tag>Example</Tag>}{isArchived(c) && <Tag tone="warn">Archived</Tag>}</span>}
      sub={<>{showValue(S, { key: 'status', label: 'Status', type: 'text' }, c.status)}{c.created_at && <> · added {ago(c.created_at)}</>}{isArchived(c) && <> · archived on {dateLong(c.archived_at)}</>}</>}
      actions={acts.length > 0 && <span className="flex items-center gap-2" data-client-actions>
        {acts.includes('restore') && <Button size="sm" icon={ArchiveRestore} onClick={() => { restoreClient(c.id).catch(() => {}); }}>Restore</Button>}
        {acts.includes('archive') && <Button size="sm" icon={Archive} onClick={() => confirm({
          title: 'Archive ' + c.client_name + '?', verb: 'Archive the client',
          body: archiveText(S, c),
          run: () => { archiveClient(c.id).catch(() => {}); },
        })}>Archive client</Button>}
        {acts.includes('delete') && <Button size="sm" variant="danger" icon={Trash2} onClick={() => confirm({
          title: 'Delete ' + c.client_name + '?', verb: 'Delete the client',
          body: 'This deletes the client and every card, call, inbox batch and number that belongs to them. It cannot be undone. To keep the history, archive the client instead.',
          run: () => { navigate({ screen: 'clients' }, true); remove('clients', c.id).then(() => toast('Client deleted.')).catch(() => {}); },
        })}>Delete</Button>}
      </span>}
      sections={sections} />
  );
}
