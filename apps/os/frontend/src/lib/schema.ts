/* One place that joins core.config.ts and agency.config.ts: every ladder, every board,
 * and the small questions the screens ask about them. */
import type { Ladders, RecordDef } from '../config';
import { CORE_LADDERS, TASKS_BOARD } from '../core.config';
import { AGENCY, LADDERS as AGENCY_LADDERS } from '../agency.config';
import { stageNumber } from './format';

export { AGENCY };

/** Every database list the screens know, by its database name. */
export const LADDERS: Ladders = { ...CORE_LADDERS, ...AGENCY_LADDERS };

/** The boards, in tab order: Tasks first, then the agency's own. */
export const BOARDS: RecordDef[] = [TASKS_BOARD, ...AGENCY.boards];

/** Tables with stages but no board (a list on the client page). */
export const LISTS: RecordDef[] = AGENCY.lists;

/** Every table with stages. */
export const RECORDS: RecordDef[] = BOARDS.concat(LISTS);

/** The tables the checklists live in (email marketing: emails). */
export const CHECKLIST_TABLES: string[] = Array.from(new Set(BOARDS.filter((b) => b.checklist).map((b) => b.checklist!.table)));

/** The board or list of a table, or null. */
export function recordDef(table?: string | null): RecordDef | null {
  return RECORDS.find((r) => r.table === table) || null;
}

/** The stages of a board, in ladder order. */
export function ladderOf(def: RecordDef): readonly string[] {
  return LADDERS[def.ladder] || [];
}

/** The choices of a database list ([] when the list is not known). */
export function listOf(name?: string): readonly string[] {
  return (name && LADDERS[name]) || [];
}

/** True while a card is still open (not in one of its board's finished stages). */
export function isOpen(def: RecordDef, row: Record<string, unknown>): boolean {
  return def.closed.indexOf(String(row[def.stageKey])) < 0;
}

/** True while a card is in a live stage: open, but never late or stuck. */
export function isLive(def: RecordDef, row: Record<string, unknown>): boolean {
  return (def.live || []).indexOf(String(row[def.stageKey])) > -1;
}

/** True when a card's due date can make it late: open and not live. */
export function canBeLate(def: RecordDef, row: Record<string, unknown>): boolean {
  return isOpen(def, row) && !isLive(def, row);
}

/** A stage whose number ends in 9 holds the work (sent back or blocked); below 0 is rejected. */
export function isHeld(stage?: string | null): boolean {
  const n = stageNumber(stage);
  return n !== null && (n < 0 || n % 10 === 9);
}

/** The next stage up the ladder from this one that is not a hold stage (null at the top). */
export function nextStage(def: RecordDef, stage: string): string | null {
  const ladder = ladderOf(def);
  const n = stageNumber(stage);
  const ahead = ladder.filter((s) => {
    const m = stageNumber(s);
    return m !== null && n !== null && m > n && m >= 0 && m % 10 !== 9;
  });
  return ahead.length ? ahead[0] : null;
}

/** The link to a card. Slack posts and the dashboard use the same shape:
 *  /board/<table>/<row id> (and /clients/<id> for a client). */
export function cardPath(table: string, id: string): string {
  return '/board/' + encodeURIComponent(table) + '/' + encodeURIComponent(id);
}
