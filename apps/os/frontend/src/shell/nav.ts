/* The side menu and each screen's header: title, description, and the one button. */
import { ClipboardList, House, LayoutDashboard, SquareKanban, Users, UserRound, type LucideIcon } from 'lucide-react';
import type { Route, ScreenId } from '../lib/router';
import type { Data } from '../lib/store';
import type { ScreenFilterValue } from '../lib/ui';
import { BOARDS } from '../lib/schema';
import { assigneeKey, openCount } from '../areas/tasks/assignee';

/** The screens, in menu order: [list screen, label, icon]. My Work is the home page (/). */
export const NAV: Array<[ScreenId, string, LucideIcon]> = [
  ['home', 'My Work', House],
  ['dashboard', 'Dashboard', LayoutDashboard],
  ['tasks', 'Tasks', SquareKanban],
  ['clients', 'Clients', Users],
  ['team', 'Team', UserRound],
  ['forms', 'Onboarding forms', ClipboardList],
];

/** The menu item a screen lights up (a client page lights Clients). */
export function navFor(s: ScreenId): ScreenId {
  return s === 'client' ? 'clients' : s === 'member' ? 'team' : s;
}

/** The count beside a menu item (null for none). Tasks counts the open cards each board's
 *  Assignee filter lets through (Me unless changed), as the tabs do. */
export function navCount(S: Data, s: ScreenId, f: Record<string, ScreenFilterValue>): number | null {
  const meId = S.me ? S.me.id : null;
  if (s === 'tasks') return BOARDS.reduce((n, b) => n + openCount(b, S.rows(b.table), f[assigneeKey(b.table)], meId), 0);
  if (s === 'clients') return S.activeClients.length;
  if (s === 'team') return S.activeTeam.length;
  return null;
}

/** [emoji, line] under each screen's title. */
export const DESC: Partial<Record<ScreenId, [string, string]>> = {
  home: ['👋', 'What waits on you, and what you handed on to someone else. Click a row to open the card.'],
  dashboard: ['📊', 'What is stuck or late, who is overloaded, and which clients need attention. Click any item to open it.'],
  tasks: ['🗂️', 'One tab per board. Drag a card to its next stage, or open it to work on it.'],
  clients: ['🤝', 'Every client. Open one to see and edit everything about them.'],
  team: ['👥', 'Who is on the team, what they can do, and how much they hold.'],
  forms: ['📝', 'Every onboarding form a client has sent. Open one to read the answers.'],
};

/** The page title. */
export function headTitle(S: Data, r: Route): string {
  switch (r.screen) {
    case 'client': return (r.id && S.clientById[r.id] && S.clientById[r.id].client_name) || 'Client';
    case 'member': return (r.id && S.teamById[r.id] && S.teamById[r.id].full_name) || 'Team member';
    case 'tasks': return 'Tasks';
    default: return (NAV.find((n) => n[0] === r.screen) || NAV[0])[1];
  }
}

/** Record pages carry a back button. */
export const RECORD_PAGE: ScreenId[] = ['client', 'member'];
/** Screens whose body fills the page and scrolls inside itself (the board). */
export const BOARD_PAGE: ScreenId[] = ['tasks'];
