/* A copy document on a card or on the client page: "Open editor", how long it is, and who
 * saved it last. Under it, "paste a link instead" for copy that lives somewhere else (a
 * Google Doc): that saves to the field's link column, as before documents existed. */
import { useState } from 'react';
import { FileText } from 'lucide-react';
import type { FieldDef } from '../../config';
import { Button, LinkRow, TextInput } from '../../ui';
import { patch, useData, type Row } from '../../lib/store';
import { useDocs } from '../../lib/documents';
import { openDoc } from '../../lib/router';
import { wait } from '../../lib/format';
import { canChangeDoc } from '../../lib/docaccess';

/** "just now", "12 min ago", "5h ago", "3d ago". */
export function ago(ts?: string | null): string {
  if (!ts) return '';
  const mins = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + ' min ago';
  return wait(ts) + ' ago';
}

/** Where a document of this row lives: its client, and its board and card (none on the client page). */
export function docPlace(table: string, row: Row): { client: string | null; board: string | null; card: string | null } {
  return table === 'clients' ? { client: row.id, board: null, card: null } : { client: row.client_id || null, board: table, card: row.id };
}

export function DocField({ table, row, f, canEdit }: { table: string; row: Row; f: FieldDef; canEdit: boolean }) {
  const S = useData();
  const at = docPlace(table, row);
  const q = useDocs(at.client || '', at.board, at.card);
  const [linkOpen, setLinkOpen] = useState(false);
  const doc = (q.rows || []).find((d) => d.field_key === f.key);
  const link = f.link ? String(row[f.link] || '') : '';
  const write = canEdit && canChangeDoc(S.me && S.me.access, at.board);

  const info = q.missing ? 'Documents need database change 0013.'
    : !at.client ? 'Pick a client for this card first: a document belongs to a client.'
    : doc && (doc.version > 1 || doc.word_count > 0) ? (doc.word_count || 0).toLocaleString() + ' words · saved ' + ago(doc.updated_at) + (S.teamName(doc.updated_by) ? ' by ' + S.teamName(doc.updated_by) : '')
    : q.rows ? 'Nothing written yet.' : '';
  return (
    <div className="space-y-1.5 min-w-0" data-doc-field={f.key}>
      <div className="flex items-center gap-2.5 flex-wrap">
        {at.client && !q.missing
          ? <Button size="sm" icon={FileText} onClick={() => openDoc(f.key)}>{write ? 'Open editor' : 'Read'}</Button>
          : <Button size="sm" icon={FileText} disabled>Open editor</Button>}
        {info && <span className={`text-[12px] ${q.missing ? 'text-bad' : 'text-muted'}`}>{info}</span>}
      </div>
      {f.link && link && <LinkRow url={link} label="Open the link" />}
      {f.link && canEdit && (linkOpen || link
        ? <TextInput type="url" aria-label={f.label + ' link'} field={table + ':' + row.id + ':' + f.link} value={link} placeholder="https://"
            onSave={(x) => { const v = x.trim() || null; if (v !== (link || null)) patch(table, row.id, { [f.link as string]: v }).catch(() => {}); }} />
        : <button type="button" className="text-[11.5px] text-muted underline underline-offset-2 hover:text-ink2" onClick={() => setLinkOpen(true)}>paste a link instead</button>)}
    </div>
  );
}
