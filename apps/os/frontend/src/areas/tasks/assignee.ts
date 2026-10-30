/* The Assignee filter on each board tab. "Me" is the default, so a person opens the board
 * on their own cards. The choice is kept per board in this browser (lib/ui.ts):
 *   nothing kept  -> Me
 *   'me'          -> Me (whoever is signed in)
 *   ''            -> Everyone
 *   a team id     -> that person
 * Signed in but not on the team list: there is no Me, so the default is Everyone.
 * The sidebar's Tasks count and the tab counts use the same choice.
 *
 * No imports but types: tests/work.test.mjs runs this file in Node as it is. */
import type { RecordDef } from '../../config';
import type { Row } from '../../lib/db';

export const ME = 'me';

/** The filter key of a board's Assignee choice. */
export const assigneeKey = (table: string) => 'tasks:' + table + ':person';

/** The kept choice, with the default filled in: 'me', '' (Everyone) or a team id. */
export function assigneeChoice(kept: unknown, meId: string | null): string {
  const v = typeof kept === 'string' ? kept : ME;
  return v === ME && !meId ? '' : v;
}

/** The team id the board shows, or '' for everyone. */
export function assigneeId(kept: unknown, meId: string | null): string {
  const v = assigneeChoice(kept, meId);
  return v === ME ? (meId as string) : v;
}

/** True when a card passes the board's Assignee choice. */
export function passesAssignee(row: Row, kept: unknown, meId: string | null): boolean {
  const id = assigneeId(kept, meId);
  return !id || row.assignee_id === id;
}

/** The open cards a board's tab counts, under its Assignee choice. */
export function openCount(def: RecordDef, rows: Row[], kept: unknown, meId: string | null): number {
  return rows.filter((r) => def.closed.indexOf(String(r[def.stageKey])) < 0 && passesAssignee(r, kept, meId)).length;
}
