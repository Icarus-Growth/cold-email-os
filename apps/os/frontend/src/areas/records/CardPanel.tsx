/* The card panel: one card of any board (or a list with no board), on the right of the page.
 * Stage first (with the button that moves the card on), then the board's own sections from
 * agency.config.ts, then the checklist (if the board has one), any extra columns, the stage
 * history, and the ids for developers. "Delete" sits at the top and nowhere else. */
import { useState } from 'react';
import { Link2, Plus, Trash2, X } from 'lucide-react';
import type { ChecklistDef, RecordDef } from '../../config';
import { Button, Notice, RecordPanel, Select, StagePill, TextInput, type SectionSpec } from '../../ui';
import { insert, move, patch, remove, useData, useQuery, type Data, type Row } from '../../lib/store';
import { cardPath, isHeld, ladderOf, listOf, nextStage, recordDef } from '../../lib/schema';
import { closeCard } from '../../lib/router';
import { confirm, toast } from '../../lib/ui';
import { dateTime, shortStage, wait } from '../../lib/format';
import { devSection, extraFields, keysOf, sectionSpec } from './fields';

/** Copy text, with a fallback for browsers that block the clipboard. */
export function copyText(text: string, done = 'Copied.'): void {
  const ok = () => toast(done, 'good');
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(ok, () => prompt('Copy this:', text));
  } else prompt('Copy this:', text);
}

function StageSection(S: Data, def: RecordDef, row: Row): SectionSpec {
  const ladder = ladderOf(def);
  const stage = String(row[def.stageKey] || '');
  const next = nextStage(def, stage);
  const by = S.teamName(row.stage_changed_by_id);
  const since = row.stage_changed_at || row.created_at;
  return {
    title: 'Stage',
    desc: isHeld(stage) ? 'This card is held: it was sent back or is blocked. Fix what the feedback asks, then move it on.'
      : 'Move the card when your part is done. The move is saved at once and written to the stage log.',
    state: 'current',
    button: next ? { label: 'Move to ' + shortStage(next), primary: true, onClick: () => { move(def.table, row.id, next).catch(() => {}); } } : null,
    fields: [
      { k: 'Stage', node: <Select large aria-label="Stage" value={stage} options={ladder.map((s): [string, string] => [s, s])}
        onChange={(s) => { move(def.table, row.id, s).catch(() => {}); }} /> },
      { k: 'In this stage', v: wait(since) + (by ? ' · moved by ' + by : '') },
    ],
  };
}

/** The checklist inside a card (email marketing: the emails of a flow or a calendar). */
function Checklist({ c, card }: { c: ChecklistDef; card: Row }) {
  const S = useData();
  const [name, setName] = useState('');
  const items = S.rows(c.table).filter((r) => r[c.parentKey] === card.id)
    .sort((a, b) => (Number(a[c.orderKey]) || 0) - (Number(b[c.orderKey]) || 0));
  const statuses = listOf(c.statusList);
  const done = items.filter((r) => r[c.statusKey] === statuses[statuses.length - 1]).length;
  function add() {
    const n = name.trim();
    if (!n) return;
    setName('');
    insert(c.table, { [c.nameKey]: n, client_id: card.client_id, [c.parentKey]: card.id,
                      [c.orderKey]: items.length ? Math.max(...items.map((r) => Number(r[c.orderKey]) || 0)) + 1 : 1 }).catch(() => {});
  }
  return (
    <div className="space-y-1.5" data-checklist={c.table}>
      <div className="text-[12.5px] text-muted">{done} of {items.length} {statuses[statuses.length - 1].toLowerCase()}</div>
      {items.map((r) => (
        <div key={r.id} className="grid grid-cols-[1fr_150px_30px] max-[520px]:grid-cols-[1fr_110px_30px] gap-2 items-center" data-checklist-item={r.id}>
          <TextInput aria-label="Email name" value={r[c.nameKey]} onSave={(v) => { if (v.trim()) patch(c.table, r.id, { [c.nameKey]: v.trim() }).catch(() => {}); }} />
          <Select aria-label="Status" value={String(r[c.statusKey] || '')} options={statuses.map((s): [string, string] => [s, s])}
            onChange={(v) => { patch(c.table, r.id, { [c.statusKey]: v }).catch(() => {}); }} />
          <button type="button" aria-label={'Delete ' + r[c.nameKey]} className="inline-flex items-center justify-center w-[30px] h-[30px] rounded-[8px] text-faint hover:text-bad hover:bg-tbad"
            onClick={() => confirm({ title: 'Delete this email?', body: '"' + r[c.nameKey] + '" is removed from the checklist. This cannot be undone.', verb: 'Delete',
              run: () => { remove(c.table, r.id).catch(() => {}); } })}><X size={14} /></button>
        </div>
      ))}
      <form className="flex gap-2 pt-1" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Add an email, for example Email 1: Welcome"
          aria-label="New email" className="flex-1 min-w-0 h-[34px] rounded-[10px] border border-line bg-card px-3 text-[13px] focus:outline-none focus:border-[var(--border-focus)]" />
        <Button size="md" icon={Plus} type="submit" disabled={!name.trim()}>Add</Button>
      </form>
    </div>
  );
}

/** The stage log of one card, newest first. */
function History({ table, id }: { table: string; id: string }) {
  const S = useData();
  const q = useQuery({ key: 'log:' + table + ':' + id, table: 'stage_log', ttl: 0,
    opts: { filter: 'board=eq.' + encodeURIComponent(table) + '&record_id=eq.' + encodeURIComponent(id), order: 'changed_at.desc', limit: 30 } });
  if (!q.rows) return <div className="text-[12.5px] text-faint">Loading…</div>;
  if (!q.rows.length) return <div className="text-[12.5px] text-faint">No moves yet.</div>;
  return (
    <ul className="space-y-1.5 text-[12.5px]" data-history>
      {q.rows.slice(0, 30).map((e) => (
        <li key={e.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-muted tnum w-[150px] shrink-0">{dateTime(e.changed_at)}</span>
          {e.from_stage ? <><StagePill stage={e.from_stage} /><span className="text-faint">to</span></> : <span className="text-muted">Added in</span>}
          <StagePill stage={e.to_stage} />
          {e.changed_by_id && <span className="text-muted">by {S.teamName(e.changed_by_id) || 'someone'}</span>}
        </li>
      ))}
    </ul>
  );
}

export function CardPanel({ table, id }: { table: string; id: string }) {
  const S = useData();
  const def = recordDef(table);
  const row = def ? S.row(table, id) : null;
  if (!def || !row) {
    return (
      <RecordPanel crumb={def ? def.label : 'Card'} title="This card is not here" onClose={closeCard} sections={[]}>
        <Notice title="It may have been deleted, or the link is wrong.">Close this panel to go back.</Notice>
      </RecordPanel>
    );
  }
  const shown = [def.nameKey, def.stageKey, 'client_id', ...keysOf(def.sections.flatMap((s) => s.fields))];
  const extras = extraFields(row, shown);
  const name = String(row[def.nameKey] || 'Untitled ' + def.item);
  const link = (S.settings.os_url ? String(S.settings.os_url).replace(/\/+$/, '') : location.origin) + cardPath(table, id);
  const sections: Array<SectionSpec | null> = [
    StageSection(S, def, row),
    ...def.sections.map((s) => sectionSpec(S, table, row, s)),
    def.checklist ? { title: def.checklist.label, desc: 'Each one moves from to-do to done. The card moves on its own ladder above.',
                      children: <Checklist c={def.checklist} card={row} /> } : null,
    extras.length ? sectionSpec(S, table, row, { title: 'More fields', desc: 'Columns this table has that the screens do not name yet.', fields: extras }) : null,
    { title: 'Stage history', desc: 'Every move of this card, written by the database.', fold: true, closed: true, foldKey: 'history',
      children: <History table={table} id={id} /> },
    devSection(S, table, row),
  ];
  return (
    <RecordPanel crumb={def.label} title={name} colour={row.client_id ? S.clientColour(row.client_id) : undefined}
      sub={(row.client_id ? S.clientName(row.client_id) : 'No client') + (row.archived_at ? ' · archived: hidden from the boards and the dashboard' : '')}
      ladder={ladderOf(def)} stage={row[def.stageKey]} onClose={closeCard}
      actions={<>
        <Button size="sm" icon={Link2} onClick={() => copyText(link, 'Link copied.')}>Copy link</Button>
        <Button size="sm" variant="danger" icon={Trash2} onClick={() => confirm({
          title: 'Delete this ' + def.item + '?', body: '"' + name + '" is deleted for everyone. This cannot be undone.', verb: 'Delete',
          run: () => { closeCard(); remove(table, id).then(() => toast('Deleted.')).catch(() => {}); },
        })}>Delete</Button>
      </>}
      sections={sections} />
  );
}
