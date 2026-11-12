/* AREA: home. My Work, the first screen after sign-in (/). The numbers and charts stay on
 * the Dashboard.
 *
 * Top to bottom, for the signed-in person:
 *   1. a greeting and one "New" button per board;
 *   2. Waits on you: every open card where this person acts next (work.ts says who);
 *   3. Waits on others: what they hold or moved last, and who it waits on now;
 *   4. one line: the stage moves on their cards since yesterday.
 * An Owner or Admin can pick whose work to see ("View as", work.ts whoseWork); a Member sees their own.
 * One filter bar over both sections (Client, Board, Stage, Due date: AND across, OR inside
 * one). Each section groups on its own (None, Client, Board, Stage, Due), with folding group
 * headers, and sorts on its own (Default, or a field up or down; inside groups the groups keep
 * their order). Every choice is remembered in this browser (lib/ui.ts). Archived cards never
 * show: the store leaves them out. */
import { ArrowRight, Plus } from 'lucide-react';
import { Button, ChoicePill, DataTable, Dot, Foot, MultiPill, RangePill, SortPill, Stack, addDays, readSort, resolveRange, sortList, writeSort, type Column, type TableGroup } from '../../ui';
import { useData, useQuery, type Data, type Row } from '../../lib/store';
import { BOARDS, ladderOf } from '../../lib/schema';
import { RULES } from '../../lib/rules';
import { inApp, openCard } from '../../lib/router';
import { clearScreenFilters, createOpen, filterValue, filterValues, screenFilters, setScreenFilter, toggleScreenFilter } from '../../lib/ui';
import { dateShort, dayKey, shortStage, wait } from '../../lib/format';
import { openWork, sinceYesterday, waitsOnOthers, waitsOnYou, whoseWork, type Move, type WorkItem } from './work';

const CARD = 'rounded-[14px] bg-card border border-line shadow-[var(--shadow-sm)]';

/* Filter keys. "View as" and each section's Group by and Sort sit outside "home:", so
 * Clear filters leaves them. */
const K = { client: 'home:client', board: 'home:board', stage: 'home:stage', due: 'home:due', viewAs: 'homeV:viewas',
  group: { you: 'homeG:you', others: 'homeG:others' }, sort: { you: 'homeS:you', others: 'homeS:others' } };
const DUE_OPTIONS = ['any', 'late', 'today', 'next7', 'between', 'none'];

type Which = 'you' | 'others';
type GroupBy = 'none' | 'client' | 'board' | 'stage' | 'due';
const GROUP_BY: Array<[GroupBy, string]> = [['none', 'None'], ['client', 'Client'], ['board', 'Board'], ['stage', 'Stage'], ['due', 'Due']];
const DUE_GROUPS = ['Late', 'Today', 'This week', 'Later', 'No date', 'Live'];

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/** A stage as the Stage filter and the Stage groups name it: "Tasks · In Review". */
const stageLabel = (w: { board: string; stage: string }) => w.board + ' · ' + shortStage(w.stage);
/** A card's place: board order first, then ladder order. */
function stageRank(w: WorkItem): number {
  const b = BOARDS.findIndex((d) => d.table === w.table);
  const i = b < 0 ? -1 : ladderOf(BOARDS[b]).indexOf(w.stage);
  return b * 100 + (i < 0 ? 99 : i);
}
/** Late, Today, This week (the next 7 days, as the Due filter counts them), Later, No date, Live (running, never late). */
function dueGroup(w: WorkItem, today: string): string {
  if (w.live) return 'Live';
  if (!w.due) return 'No date';
  if (w.late) return 'Late';
  if (w.due === today) return 'Today';
  return w.due <= addDays(today, 6) ? 'This week' : 'Later';
}

interface Sel { clients: string[]; boards: string[]; stages: string[]; due: string }
/** AND across the filters, OR inside one. An empty filter lets everything through. */
function passes(S: Data, w: WorkItem, f: Sel, today: string): boolean {
  if (f.clients.length && f.clients.indexOf(S.clientName(w.clientId)) < 0) return false;
  if (f.boards.length && f.boards.indexOf(w.board) < 0) return false;
  if (f.stages.length && f.stages.indexOf(stageLabel(w)) < 0) return false;
  if (f.due === 'any') return true;
  if (f.due === 'late') return w.late;
  if (f.due === 'none') return !w.due;
  const r = resolveRange(f.due, today);
  return !r || (!!w.due && w.due >= r.from && w.due <= r.to);
}

/** The groups of a list in their fixed order; empty groups are left out. The list's own order
 *  holds inside each group. Client A–Z (no client last), Board and Stage in board order, Due
 *  from Late to No date. */
function groupWork(S: Data, list: WorkItem[], by: GroupBy, today: string): Array<{ key: string; label: string; colour?: string; items: WorkItem[] }> {
  const keyOf = (w: WorkItem): [string, string, string] => {  // key, label, sort key
    if (by === 'client') return w.clientId ? [w.clientId, S.clientName(w.clientId), '0' + S.clientName(w.clientId).toLowerCase()] : ['none', 'No client', '1'];
    if (by === 'board') return [w.table, w.board, String(BOARDS.findIndex((d) => d.table === w.table)).padStart(3, '0')];
    if (by === 'stage') return [w.table + '|' + w.stage, stageLabel(w), String(stageRank(w)).padStart(5, '0')];
    const g = dueGroup(w, today);
    return [g, g, String(DUE_GROUPS.indexOf(g))];
  };
  const groups: Record<string, { key: string; label: string; colour?: string; items: WorkItem[]; sort: string }> = {};
  list.forEach((w) => {
    const [key, label, sort] = keyOf(w);
    (groups[key] = groups[key] || { key, label, sort, items: [], colour: by === 'client' && w.clientId ? S.clientColour(w.clientId) : undefined }).items.push(w);
  });
  return Object.values(groups).sort((a, b) => a.sort.localeCompare(b.sort)).map(({ sort, ...g }) => { void sort; return g; });
}

/** The fields a section sorts on, and how each is read off a card (empty = no value). */
function sortFields(S: Data): Array<[string, string, (w: WorkItem) => string | number | null]> {
  return [
    ['due', 'Due', (w) => w.due],
    ['in_stage', 'Time in stage', (w) => (w.since ? Date.now() - new Date(w.since).getTime() : null)],
    ['name', 'Name', (w) => w.name],
    ['client', 'Client', (w) => (w.clientId ? S.clientName(w.clientId) : null)],
    ['board', 'Board', (w) => BOARDS.findIndex((d) => d.table === w.table)],
    ['stage', 'Stage', (w) => stageRank(w)],
  ];
}

/** The due cell: "Late since 08 Oct" / "Due today" / "Due 13 Oct", and with no due date,
 *  how long it has waited in its stage. A live card: "Live for 12d" (never late). */
function when(w: WorkItem, today: string): { text: string; tone: 'bad' | 'warn' | null } {
  const t = wait(w.since);
  if (w.live) return { text: t === '—' || t === 'just now' ? 'Live' : 'Live for ' + t, tone: null };
  if (w.due) {
    if (w.late) return { text: 'Late since ' + dateShort(w.due + 'T00:00:00'), tone: 'bad' };
    if (w.due === today) return { text: 'Due today', tone: 'warn' };
    return { text: 'Due ' + dateShort(w.due + 'T00:00:00'), tone: null };
  }
  return { text: t === '—' ? '—' : t === 'just now' ? 'Waiting under 1h' : 'Waiting ' + t, tone: null };
}

/* The rows the tables draw: only the fields they show, so "Add column" offers nothing odd. */
function rows(S: Data, list: WorkItem[]): Row[] {
  return list.map((w) => ({ id: w.id, name: w.name, board: w.board, stage: shortStage(w.stage), client: S.clientName(w.clientId),
    waits_on: w.waiter ? S.teamName(w.waiter) || '—' : 'Nobody', in_stage: wait(w.since), _w: w }) as Row);
}

/** The start of yesterday, as the database writes times. */
function yesterdayStart(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - 1);
  return d.toISOString();
}

export function Home() {
  const S = useData();
  const f = screenFilters.use();
  const today = dayKey(new Date());

  /* Whose work: the signed-in person; an Owner or Admin can pick anyone under "View as". */
  const who = whoseWork(S.me, S.activeTeam, filterValue(f, K.viewAs, ''));
  const person = who.person;
  const id: string | null = person ? person.id : null;
  /* Someone else's work: the titles name them, not "you". */
  const other = person && (!S.me || person.id !== S.me.id) ? String(person.full_name || '').split(' ')[0] || 'them' : null;
  const you = other || 'you';

  const all = openWork({ boards: BOARDS, rows: (t) => S.rows(t), clientById: S.clientById, team: S.raw.team || [], rules: RULES, today });
  const mineAll = id ? waitsOnYou(all, id) : [];
  const handedAll = id ? waitsOnOthers(all, id) : [];

  /* The filter bar: options come from this person's own work (plus anything still ticked). */
  const boardNames = BOARDS.map((b) => b.label);
  const boards = filterValues(f, K.board).filter((b) => boardNames.indexOf(b) > -1);
  const stageOptions = BOARDS.filter((b) => !boards.length || boards.indexOf(b.label) > -1)
    .flatMap((b) => ladderOf(b).filter((x) => b.closed.indexOf(x) < 0).map((x) => stageLabel({ board: b.label, stage: x })));
  const ticked = filterValues(f, K.client);
  const clientOptions = Array.from(new Set(mineAll.concat(handedAll).map((w) => S.clientName(w.clientId)).concat(ticked)))
    .sort((a, b) => a.localeCompare(b));
  const sel: Sel = { clients: ticked, boards, stages: filterValues(f, K.stage).filter((x) => stageOptions.indexOf(x) > -1), due: filterValue(f, K.due, 'any') };
  const anyFilter = sel.clients.length + sel.boards.length + filterValues(f, K.stage).length > 0 || sel.due !== 'any';

  /* Sort: Default keeps each section's own order; a field sorts the filtered list, then groups
   * cut it, so the groups keep their own order and the sort holds inside each. */
  const fields = sortFields(S);
  const sortOf = (which: Which) => readSort(filterValue(f, K.sort[which], 'default'));
  const sorted = (list: WorkItem[], which: Which) => {
    const c = sortOf(which);
    const field = fields.find((x) => x[0] === c.field);
    return field ? sortList(list, field[2], c.dir) : list;
  };
  const orderNote = (which: Which, byDefault: string) => {
    const c = sortOf(which);
    const field = fields.find((x) => x[0] === c.field);
    return field ? 'Sorted by ' + field[1].toLowerCase() + ', ' + (c.dir === 'asc' ? 'ascending' : 'descending') + '.' : byDefault;
  };
  const mine = sorted(mineAll.filter((w) => passes(S, w, sel, today)), 'you');
  const handed = sorted(handedAll.filter((w) => passes(S, w, sel, today)), 'others');
  const groupOf = (which: Which) => {
    const v = filterValue(f, K.group[which], 'none');
    return (GROUP_BY.find((g) => g[0] === v) || GROUP_BY[0])[0];
  };
  const groups = (list: WorkItem[], which: Which): TableGroup[] | undefined => {
    const by = groupOf(which);
    return by === 'none' ? undefined : groupWork(S, list, by, today).map((g) => ({ key: g.key, label: g.label, colour: g.colour, rows: rows(S, g.items) }));
  };
  const groupPill = (which: Which) => (
    <div className="ml-auto flex items-center gap-2 flex-wrap max-[720px]:ml-0" data-group-by={which}>
      <ChoicePill label="Group by" value={(GROUP_BY.find((g) => g[0] === groupOf(which)) || GROUP_BY[0])[1]} options={GROUP_BY.map((g) => g[1])}
        onChange={(v) => setScreenFilter(K.group[which], (GROUP_BY.find((g) => g[1] === v) || GROUP_BY[0])[0])} />
      <SortPill fields={fields.map((x) => [x[0], x[1]] as [string, string])} choice={sortOf(which)} onChange={(c) => setScreenFilter(K.sort[which], writeSort(c))} />
    </div>
  );

  /* Since yesterday: the stage log from the start of yesterday (one load, kept 1 minute). */
  const from = yesterdayStart();
  const log = useQuery({ key: 'home:moves:' + from, table: 'stage_log', ttl: 60000, acceptsInserts: false,
    opts: { select: 'board,record_id,from_stage,to_stage,changed_at', filter: 'changed_at=gte.' + encodeURIComponent(from), order: 'changed_at.desc' } });
  const moves = id && log.rows && !log.missing ? sinceYesterday({ boards: BOARDS, rows: (t) => S.rows(t), clientById: S.clientById, team: [], rules: [], today }, log.rows as unknown as Move[], id) : null;
  const first = S.me ? String(S.me.full_name || '').split(' ')[0] : '';

  const nameCol: Column = { label: 'Name', w: 260, cell: (r) => ({ node: (
    <span className="flex items-center gap-2.5 min-w-0" data-work-row={r.id}>
      <Dot colour={S.clientColour(r._w.clientId)} size={9} /><span className="font-medium text-ink truncate">{r.name}</span>
    </span>) }) };
  const base: Record<string, Column> = {
    name: nameCol,
    board: { label: 'Board', w: 120, cell: (r) => ({ t: r.board }) },
    stage: { label: 'Stage', w: 170, cell: (r) => ({ t: r.stage }) },
    client: { label: 'Client', w: 180, cell: (r) => ({ t: r.client }) },
  };
  const mineCols: Record<string, Column> = {
    ...base,
    when: { label: 'Due or waiting', w: 170, cell: (r) => { const x = when(r._w, today); return { node: <span data-when={x.text} data-late={r._w.late ? '' : undefined}>{x.text}</span>, tone: x.tone }; } },
  };
  const handedCols: Record<string, Column> = {
    ...base,
    waits_on: { label: 'Waits on', w: 150, cell: (r) => ({ node: <span data-waits-on={r.waits_on}>{r.waits_on}</span>, tone: r._w.waiter ? null : 'warn' }) },
    in_stage: { label: 'In this stage', w: 120, align: 'right', cell: (r) => ({ t: r.in_stage }) },
  };
  const open = (r: Row) => openCard(r._w.table, r.id);
  const count = (n: number) => <span className="ml-1.5 font-normal text-muted tnum" data-count={n}>({n})</span>;

  return (
    <div className="min-w-0" data-home data-my-work>
      <Stack>
        <section className={`${CARD} px-5 py-4 flex flex-col gap-3`} data-greeting>
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-[20px] font-semibold text-ink" data-hello>{greeting()}{first ? ', ' + first : ''}</h2>
            <a href="/dashboard" onClick={(e) => inApp(e, '/dashboard')} className="ml-auto text-[12.5px] text-ink2 inline-flex items-center gap-1 hover:text-ink no-underline" data-dashboard-link>
              Dashboard<ArrowRight size={13} />
            </a>
          </div>
          <div className="flex items-center gap-2 flex-wrap" data-quick>
            {BOARDS.map((b) => (
              <Button key={b.table} variant="outline" size="sm" icon={Plus} onClick={() => createOpen.set({ table: b.table })} data-quick-new={b.table}>
                {'New ' + b.item}
              </Button>
            ))}
          </div>
          {who.canPick && (
            <div data-view-as>
              <ChoicePill label="View as" value={person ? person.full_name : ''} options={who.options} onChange={(v) => setScreenFilter(K.viewAs, v)} />
              <p className="mt-1 text-[12.5px] text-muted" data-view-as-help>
                {!S.me ? 'You are not on the team list, so you see the work of the person you pick.'
                  : other ? 'You see ' + person!.full_name + '\'s work: what waits on them, and what they handed on. Pick yourself to go back.'
                  : 'Owners and Admins can see any team member\'s work here. Members see only their own.'}
              </p>
            </div>
          )}
        </section>

        <div className="flex items-center gap-2 flex-wrap" data-filters data-work-filters>
          <MultiPill label="Client" values={ticked} options={clientOptions} onToggle={(v) => toggleScreenFilter(K.client, v)} />
          <MultiPill label="Board" values={boards} options={boardNames} onToggle={(v) => toggleScreenFilter(K.board, v)} />
          <MultiPill label="Stage" values={sel.stages} options={stageOptions} onToggle={(v) => toggleScreenFilter(K.stage, v)} />
          <RangePill label="Due date" value={sel.due} options={DUE_OPTIONS} onChange={(v) => setScreenFilter(K.due, v)} />
          {anyFilter && <button type="button" className="h-[32px] px-3 rounded-full text-[13px] text-muted hover:text-ink" onClick={() => clearScreenFilters('home')}>Clear filters</button>}
          {groupPill('you')}
        </div>

        <div data-waits="you">
          <DataTable view="home-waits-on-you" rows={rows(S, mine)} cols={mineCols}
            title={<>Waits on {you}{count(mine.length)}<span className="ml-1.5 font-normal text-[12.5px] text-muted max-[1100px]:hidden" data-order-note>{orderNote('you', 'Late first, then due soonest, then longest in its stage. Live cards last.')}</span></>}
            defaults={['name', 'board', 'stage', 'client', 'when']}
            rowTone={(r) => (r._w.late ? 'bad' : null)} onRowClick={open} groups={groups(mine, 'you')}
            hidden={['_w']} empty={!id ? 'Pick a person to see their work.' : anyFilter && mineAll.length ? 'Nothing that waits on ' + you + ' matches the filters.' : 'Nothing waits on ' + you + ' right now.'} />
        </div>

        <div data-waits="others">
          <DataTable view="home-waits-on-others" rows={rows(S, handed)} cols={handedCols}
            title={<>Waits on others{count(handed.length)}<span className="ml-1.5 font-normal text-[12.5px] text-muted max-[1100px]:hidden">What {other ? other + ' holds' : 'you hold'} or moved last, and who it waits on now. {orderNote('others', 'Longest waiting first.')}</span></>}
            defaults={['name', 'board', 'stage', 'waits_on', 'in_stage']}
            onRowClick={open} groups={groups(handed, 'others')} hidden={['_w']} right={groupPill('others')}
            rowTone={(r) => (r._w.waiter ? null : 'warn')}
            empty={!id ? 'Pick a person to see their work.' : anyFilter && handedAll.length ? 'Nothing ' + (other ? other + ' handed' : 'you handed') + ' on matches the filters.' : 'Nothing ' + (other ? other + ' handed' : 'you handed') + ' on is waiting.'} />
        </div>

        {moves && (
          <p className="text-[13px] text-ink2 px-1" data-since>
            Since yesterday: <b className="text-ink tnum">{moves.moved}</b> moved, <b className="text-ink tnum">{moves.finished}</b> finished, <b className="text-ink tnum">{moves.sentBack}</b> sent back.
          </p>
        )}
      </Stack>
      <Foot>A card waits on the person the Slack alerts tag for its stage (the assignee, unless the stage is a review or another hand-off). "Nobody" means no one the alert names is filled in: give the card a person. A row opens the card. A group header folds its group. The filters, groups and sorts are remembered in this browser. "Since yesterday" counts the stage moves on the cards you are assignee or reviewer on, from midnight yesterday.</Foot>
    </div>
  );
}
