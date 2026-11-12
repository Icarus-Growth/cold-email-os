/* My Work: who must act next on every open card, worked out from the card alone.
 *
 * Who acts next is the person the Slack alert for the card's stage tags
 * (apps/os/automations/alert_rules.json, the same file the alerts and the daily summary read):
 * the first one in the rule's "tag" list who is filled in, where
 *   "assignee", "reviewer"   the card's own assignee_id / reviewer_id,
 *   "client.<column>"        that person column on the card's client (the account manager...),
 *   "owner"                  the first Owner on the team.
 * A stage with no rule uses the "new card" rule's list (assignee, then the client's account
 * manager, then the Owner). Nobody filled in: the card waits on nobody, and My Work says so.
 *
 * Waits on others: open cards this person holds (assignee) or moved last, that now wait on
 * someone else. A reviewer who sends a card back moved it last, so it shows there too.
 *
 * No imports but types: tests/work.test.mjs runs this file in Node as it is. */
import type { RecordDef } from '../../config';
import type { Row } from '../../lib/db';

/** One rule of alert_rules.json (only the parts My Work reads). */
export interface Rule { board?: string; when?: string; to?: string[]; tag?: string[] }

/** What My Work reads. The screen passes the store's data; the tests pass plain lists. */
export interface WorkSource {
  boards: RecordDef[];
  /** The rows of a board, archived rows left out. */
  rows(table: string): Row[];
  clientById: Record<string, Row>;
  /** Every team row (the alerts tag anyone on the team list). */
  team: Row[];
  rules: Rule[];
  /** Today, 'YYYY-MM-DD' in the viewer's own calendar. */
  today: string;
}

export interface WorkItem {
  id: string;
  table: string;
  /** The board's tab name ("Tasks", "Campaigns"). */
  board: string;
  name: string;
  clientId: string | null;
  stage: string;
  /** The team id of who acts next, or null for nobody. */
  waiter: string | null;
  assignee: string | null;
  /** The due day ('YYYY-MM-DD'), or null. */
  due: string | null;
  /** Due before today (on the day itself it is not late yet). Never for a live card. */
  late: boolean;
  /** In a live stage (agency.config.ts `live`): open, but running, not waiting. */
  live: boolean;
  /** When it came into this stage. */
  since: string | null;
  /** Who moved it into this stage. */
  lastBy: string | null;
}

/** The "tag" list for a card in this stage: its stage's rule, else the "new card" rule. */
export function tagsFor(rules: Rule[], table: string, stage: string): string[] {
  const mine = rules.filter((r) => r.board === '*' || r.board === table);
  const hit = mine.find((r) => (r.to || []).indexOf(stage) > -1) || mine.find((r) => r.when === 'new');
  return hit && hit.tag ? hit.tag : ['assignee'];
}

/** The team id of who acts next on a card, or null. */
export function whoActs(src: WorkSource, table: string, row: Row, stage: string): string | null {
  const onTeam = (id: unknown): id is string => typeof id === 'string' && src.team.some((t) => t.id === id);
  for (const target of tagsFor(src.rules, table, stage)) {
    let v: unknown;
    if (target === 'owner') {
      const owner = src.team.filter((t) => t.access === 'Owner' && (t.status || 'Active') === 'Active')
        .sort((a, b) => String(a.full_name).localeCompare(String(b.full_name)))[0];
      v = owner ? owner.id : null;
    } else if (target.indexOf('client.') === 0) {
      v = (src.clientById[row.client_id] || {})[target.slice(7)];
    } else {
      v = row[/_id$/.test(target) ? target : target + '_id'];
    }
    if (onTeam(v)) return v;
  }
  return null;
}

/** Every open card on every board, with who it waits on. Open = not in a `closed` stage, so a
 *  live card (a live campaign) is here too: it still needs someone to watch it. */
export function openWork(src: WorkSource): WorkItem[] {
  const out: WorkItem[] = [];
  src.boards.forEach((def) => {
    src.rows(def.table).forEach((row) => {
      const stage = String(row[def.stageKey] || '');
      if (def.closed.indexOf(stage) > -1) return;
      const due = row.due_date ? String(row.due_date).slice(0, 10) : null;
      const live = (def.live || []).indexOf(stage) > -1;
      out.push({
        id: row.id, table: def.table, board: def.label, name: String(row[def.nameKey] || 'Untitled ' + def.item),
        clientId: row.client_id || null, stage, waiter: whoActs(src, def.table, row, stage),
        assignee: row.assignee_id || null, due, late: !live && !!due && due < src.today, live,
        since: row[def.stageKey + '_changed_at'] || null, lastBy: row[def.stageKey + '_changed_by_id'] || null,
      });
    });
  });
  return out;
}

const sinceTime = (w: WorkItem) => (w.since ? new Date(w.since).getTime() : Infinity);
const dueTime = (w: WorkItem) => (w.due ? new Date(w.due + 'T00:00:00').getTime() : Infinity);

/** Late first, then due soonest, then longest in its stage. Live cards come last. */
export function byUrgency(a: WorkItem, b: WorkItem): number {
  return (Number(a.live) - Number(b.live)) || (Number(b.late) - Number(a.late)) || (dueTime(a) - dueTime(b)) || (sinceTime(a) - sinceTime(b));
}

/** What waits on this person, most urgent first. */
export function waitsOnYou(all: WorkItem[], who: string): WorkItem[] {
  return all.filter((w) => w.waiter === who).sort(byUrgency);
}

/** What this person holds or moved last and that now waits on someone else (or nobody),
 *  longest waiting first. */
export function waitsOnOthers(all: WorkItem[], who: string): WorkItem[] {
  return all.filter((w) => w.waiter !== who && (w.assignee === who || w.lastBy === who))
    .sort((a, b) => sinceTime(a) - sinceTime(b));
}

/** One stage_log row (the parts the count reads). */
export interface Move { board: string; record_id: string; from_stage: string | null; to_stage: string }

/** The stage moves on the cards this person is on (assignee or reviewer), as the daily summary
 *  counts them: moved, finished (into a finished stage), sent back (into a stage ending in 9). */
export function sinceYesterday(src: WorkSource, moves: Move[], who: string): { moved: number; finished: number; sentBack: number } {
  const mine = new Set<string>();
  const done: Record<string, string[]> = {};
  src.boards.forEach((def) => {
    done[def.table] = def.closed;
    src.rows(def.table).forEach((r) => { if (r.assignee_id === who || r.reviewer_id === who) mine.add(def.table + ':' + r.id); });
  });
  const counted = moves.filter((m) => m.from_stage && mine.has(m.board + ':' + m.record_id));
  const num = (s: string) => { const m = /^(-?\d+) - /.exec(s); return m ? Number(m[1]) : null; };
  return {
    moved: counted.length,
    finished: counted.filter((m) => (done[m.board] || []).indexOf(m.to_stage) > -1).length,
    sentBack: counted.filter((m) => { const n = num(m.to_stage); return n !== null && n > 9 && n % 10 === 9; }).length,
  };
}

/** Whose work My Work shows. An Owner or Admin picks anyone active under "View as" (themselves
 *  first, then the Owners, then everyone else); a Member sees only their own. Someone signed in
 *  who is not on the team list (the app stops them before My Work) picks too, an Owner first.
 *  `picked` is the remembered name; one that is not on the list falls back to the default. */
export function whoseWork(me: Row | null, active: Row[], picked: string): { person: Row | null; canPick: boolean; options: string[] } {
  const owners = active.filter((t) => t.access === 'Owner');
  const order = owners.concat(active.filter((t) => t.access !== 'Owner'));
  if (me && me.access !== 'Owner' && me.access !== 'Admin') return { person: me, canPick: false, options: [] };
  const list = me ? [me].concat(order.filter((t) => t.id !== me.id)) : order;
  const person = list.find((t) => t.full_name === picked) || list[0] || null;
  return { person, canPick: true, options: list.map((t) => t.full_name) };
}
