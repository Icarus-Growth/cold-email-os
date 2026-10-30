/* Onboarding forms: every submitted form, newest first. Click one to read the answers on the
 * right, and link it to a client if the form came in without one. */
import { DataTable, Notice, RecordPanel, Select, Tag, type SectionSpec } from '../../ui';
import { patch, useData, useQuery, type Row } from '../../lib/store';
import { navigate, useRoute } from '../../lib/router';
import { dateTime, readable } from '../../lib/format';
import { clientOptions } from '../records/fields';

const SPEC = { key: 'forms', table: 'onboarding_forms', opts: { order: 'submitted_at.desc' } };

/** One answer as text: lists joined, objects as their fields. */
function answer(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (Array.isArray(v)) return v.map(answer).join(', ');
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => readable(k) + ': ' + answer(x)).join('\n');
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

export function FormsTable() {
  const S = useData();
  const r = useRoute();
  const q = useQuery(SPEC);
  if (q.missing) return <Notice tone="bad" title="The forms table is not in the database yet.">Run the database set-up (tab 1) first.</Notice>;
  if (!q.rows) return <Notice title="Loading the forms…" />;
  const open = r.id ? q.rows.find((x) => x.id === r.id) || null : null;
  return (
    <>
      <DataTable view="forms" rows={q.rows} defaults={['submitted_at', 'company_name', 'client', 'submitted_by_name', 'submitted_by_email']}
        hidden={['answers', 'is_example', 'id', 'client_id']}
        cols={{
          submitted_at: { label: 'Sent', w: 170, cell: (x) => ({ t: dateTime(x.submitted_at) }) },
          company_name: { label: 'Company', w: 200, cell: (x) => ({ node: <span className="flex items-center gap-2 min-w-0"><span className="truncate font-medium text-ink">{x.company_name || '—'}</span>{x.is_example && <Tag>Example</Tag>}</span> }) },
          client: { label: 'Client', w: 200, cell: (x) => (x.client_id ? { t: S.clientName(x.client_id) } : { t: 'Not linked', tone: 'warn' }) },
          submitted_by_name: { label: 'Sent by', w: 170, cell: (x) => ({ t: x.submitted_by_name || '—' }) },
          submitted_by_email: { label: 'Email', w: 220, cell: (x) => ({ t: x.submitted_by_email || '—' }) },
        }}
        rowTone={(x) => (x.client_id ? null : 'warn')}
        onRowClick={(x) => navigate({ screen: 'forms', id: x.id })}
        empty="No forms yet. Copy a client's form link from their page and send it to them." />
      {r.id && <FormPanel row={open} />}
    </>
  );
}

function FormPanel({ row }: { row: Row | null }) {
  const S = useData();
  const close = () => navigate({ screen: 'forms' });
  if (!row) {
    return <RecordPanel crumb="Onboarding forms" title="This form is not here" onClose={close} sections={[]}>
      <Notice title="It may have been deleted, or the link is wrong." />
    </RecordPanel>;
  }
  const answers = (row.answers && typeof row.answers === 'object') ? row.answers as Record<string, unknown> : {};
  const sections: SectionSpec[] = [
    { title: 'Client', desc: 'Link the form to the client it belongs to.', fields: [
      { k: 'Client', node: <Select aria-label="Client" value={row.client_id || ''} placeholder="Not linked" options={clientOptions(S, row.client_id)}
        onChange={(v) => { patch('onboarding_forms', row.id, { client_id: v || null }).catch(() => {}); }} /> },
      ...(row.client_id ? [{ k: 'Client page', v: S.clientName(row.client_id), go: () => navigate({ screen: 'client', id: row.client_id }) }] : []),
      { k: 'Sent by', v: [row.submitted_by_name, row.submitted_by_email].filter(Boolean).join(' · ') || '—' },
      { k: 'Sent', v: dateTime(row.submitted_at) },
    ] },
    { title: 'Answers', desc: 'Exactly as the client typed them.',
      fields: Object.keys(answers).length ? Object.keys(answers).map((k) => ({ k: readable(k), v: answer(answers[k]) })) : [{ k: 'Answers', v: 'None', tone: 'mute' }] },
  ];
  return <RecordPanel crumb="Onboarding forms" title={row.company_name || 'Onboarding form'} sub={dateTime(row.submitted_at)} onClose={close} sections={sections} />;
}
