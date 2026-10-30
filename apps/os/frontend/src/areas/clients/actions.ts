/* The buttons at the top of a client page. Archive, Restore and Delete are for an Owner or Admin
 * only: a Member sees none of them.
 *
 * No imports: tests/work.test.mjs runs this file in Node as it is. */

export type ClientAction = 'archive' | 'restore' | 'delete';

export function clientActions(isAdmin: boolean, archived: boolean): ClientAction[] {
  return isAdmin ? [archived ? 'restore' : 'archive', 'delete'] : [];
}
