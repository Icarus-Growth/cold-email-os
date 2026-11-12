/* Tasks: one tab per board (agency.config.ts). Every stage on a board's ladder is a column,
 * empty or not. Drag a card to another column to move it; the database writes the move to
 * the stage log. A card shows its name and three fields, never more. */
import { Building2, CalendarClock, Hash } from 'lucide-react';
import type { RecordDef } from '../../config';
import { And, Button, ChoicePill, FilterPill, Foot, KanbanBoard, type BoardCard, type CardField } from '../../ui';
import { move, useData, type Data, type Row } from '../../lib/store';
import { BOARDS, canBeLate, ladderOf } from '../../lib/schema';
import { inApp, openCard, useRoute } from '../../lib/router';
import { clearScreenFilters, filterValue, screenFilters, setScreenFilter } from '../../lib/ui';
import { dueLine, stageNumber } from '../../lib/format';
import { linkedCard, linkedName, showNumber } from '../records/fields';
import { ME, assigneeChoice, assigneeKey, openCount, passesAssignee } from './assignee';

/** The field of a card, by its column. */
function cardField(S: Data, def: RecordDef, row: Row, key: string): CardField | null {
  const v = row[key];
  const f = def.sections.flatMap((s) => s.fields).find((x) => x.key === key);
  if (key === 'client_id') return { text: v ? S.clientName(v) : 'No client', icon: Building2 };
  /* A link to another card (ads: the creative's campaign) keeps the client on the same line. */
  if (f && f.type === 'card') {
    const client = row.client_id ? S.clientName(row.client_id) : 'No client';
    return { text: client + ' · ' + (linkedCard(S, f, v) ? linkedName(S, f, v) : 'No ' + f.label.toLowerCase()), icon: Building2 };
  }
  if (f && f.type === 'person') { const n = S.teamName(v); return { text: n || 'Nobody yet', who: n }; }
  if (f && (f.type === 'date' || f.type === 'datetime')) {
    const d = dueLine(v, f.label === 'Due date' ? 'Due' : f.label, canBeLate(def, row));
    return d ? { text: d.text, icon: CalendarClock, tone: d.tone } : { text: 'No ' + f.label.toLowerCase(), icon: CalendarClock };
  }
  if (f && (f.type === 'int' || f.type === 'number' || f.type === 'money' || f.type === 'percent')) {
    return { text: f.label + ': ' + showNumber(v, f.type), icon: Hash };
  }
  if (v === null || v === undefined || v === '') return null;
  return { text: String(v) };
}

/** A row as a board card. */
export function toCard(S: Data, def: RecordDef, row: Row): BoardCard {
  const due = row.due_date ? dueLine(row.due_date, 'Due', canBeLate(def, row)) : null;
  return {
    id: row.id,
    stage: String(row[def.stageKey]),
    title: String(row[def.nameKey] || 'Untitled ' + def.item),
    colour: row.client_id ? S.clientColour(row.client_id) : undefined,
    sort: row.updated_at,
    alert: !!(due && due.late),
    fields: (row.archived_at ? [{ text: 'Archived' } as CardField] : []).concat(
      def.card.map((k) => cardField(S, def, row, k)).filter((x): x is CardField => !!x)).slice(0, 3),
  };
}

function Tabs({ active }: { active: string }) {
  const S = useData();
  const f = screenFilters.use();
  const meId = S.me ? S.me.id : null;
  return (
    <div role="tablist" className="flex items-center gap-1 border-b border-line overflow-x-auto nosb" data-tabs>
      {BOARDS.map((b) => {
        const on = b.table === active;
        const open = openCount(b, S.rows(b.table), f[assigneeKey(b.table)], meId);
        const to = '/tasks/' + encodeURIComponent(b.table);
        return (
          <a key={b.table} role="tab" aria-selected={on} href={to} onClick={(e) => inApp(e, to)} data-tab={b.table}
            className={`shrink-0 inline-flex items-center gap-2 h-[38px] px-3 -mb-px border-b-2 text-[13.5px] no-underline ${on ? 'border-[var(--text-primary)] text-ink font-semibold' : 'border-transparent text-muted hover:text-ink'}`}>
            {b.label}<span className="text-[12px] text-muted tnum px-1.5 rounded-full bg-chrome">{open}</span>
          </a>
        );
      })}
    </div>
  );
}

export function TasksScreen() {
  const S = useData();
  const r = useRoute();
  const def = BOARDS.find((b) => b.table === r.board) || BOARDS[0];
  const f = screenFilters.use();
  const fk = 'tasks:' + def.table + ':';
  const client = filterValue(f, fk + 'client', '');
  const meId = S.me ? S.me.id : null;
  const kept = f[assigneeKey(def.table)];
  const person = assigneeChoice(kept, meId);
  const archived = filterValue(f, fk + 'archived', 'Hidden');
  const rows = (archived === 'Shown' ? S.allRows(def.table) : S.rows(def.table)).filter((row) =>
    (!client || row.client_id === client) && passesAssignee(row, kept, meId));
  const clients = S.activeClients.map((c): [string, string] => [c.id, c.client_name]);
  /* "Me" first (only for someone on the team list), then everyone else by name. */
  const people = (meId ? [[ME, 'Me'] as [string, string]] : []).concat(
    S.activeTeam.filter((t) => t.id !== meId).map((t): [string, string] => [t.id, t.full_name]));
  const notDefault = person !== assigneeChoice(undefined, meId);
  return (
    <div className="flex-1 min-h-0 flex flex-col" data-boardpage={def.table}>
      <div className="shrink-0"><Tabs active={def.table} /></div>
      <div className="shrink-0 py-3 flex items-center gap-2 flex-wrap" data-filters>
        <FilterPill label="Client" all="All clients" value={client} options={clients} onChange={(v) => setScreenFilter(fk + 'client', v)} />
        <And />
        <FilterPill label="Assignee" all="Everyone" value={person} options={people} onChange={(v) => setScreenFilter(assigneeKey(def.table), v)} />
        <ChoicePill label="Archived" value={archived} options={['Hidden', 'Shown']} onChange={(v) => setScreenFilter(fk + 'archived', v)} />
        {(client || notDefault || archived === 'Shown') && <Button size="sm" variant="ghost" onClick={() => clearScreenFilters('tasks:' + def.table)}>Clear filters</Button>}
        <span className="text-[12.5px] text-muted italic ml-auto max-[720px]:ml-0 max-[720px]:w-full">{def.desc}</span>
      </div>
      <div className="flex-1 min-h-0 -mr-10 max-[720px]:-mr-4">
        <KanbanBoard
          view={'board:' + def.table}
          stages={ladderOf(def)}
          cards={rows.map((row) => toCard(S, def, row))}
          selectedId={r.card && r.card.table === def.table ? r.card.id : null}
          onOpen={(id) => openCard(def.table, id)}
          onMove={(id, stage) => { move(def.table, id, stage).catch(() => { /* the store put it back and said so */ }); }}
          exception={(stage) => { const n = stageNumber(stage); return n !== null && n < 0; }}
        />
      </div>
      <div className="shrink-0"><Foot>Every stage gets a column, empty or not. A stage number ending in 9 means the work is held: sent back or blocked. The Assignee filter starts on Me. Pick Everyone to see the whole board; each tab keeps its own choice in this browser.</Foot></div>
    </div>
  );
}
