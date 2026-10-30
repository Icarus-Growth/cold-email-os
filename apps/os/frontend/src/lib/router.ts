/* The addresses. Every screen and every open record has its own link.
 *
 *   /                          My Work (the home page)
 *   /dashboard                 Dashboard
 *   /tasks  /tasks/<table>     Tasks, on one board's tab (the first board when none is named)
 *   /board/<table>/<id>        Tasks, that board's tab, with the card open on the right
 *                              (the link Slack posts carry; a table with no board opens over the first tab)
 *   /clients  /clients/<id>    Clients  /  one client's page
 *   /team  /team/<id>          Team  /  one person's page
 *   /forms  /forms/<id>        Onboarding forms  /  with one form open on the right
 *
 * Any screen can also carry ?card=<table>:<id> to open a card over it (the dashboard and the
 * client page do this, so closing the card goes back to where you were).
 * &doc=<field> opens that copy document in the editor, over its card (or over the client page):
 *   /board/<table>/<id>?doc=copy_doc     /clients/<id>?doc=offer_doc
 * Cloudflare Pages sends every address to index.html, so a link opened from Slack works.
 */
import { useSyncExternalStore } from 'react';
import { BOARDS } from './schema';

export type ScreenId = 'home' | 'dashboard' | 'tasks' | 'clients' | 'client' | 'team' | 'member' | 'forms';

export interface Route {
  screen: ScreenId;
  /** Tasks: the board tab. */
  board?: string;
  /** The record of a record page (client, member) or the open form. */
  id?: string;
  /** A card open on the right. */
  card?: { table: string; id: string };
  /** The copy document open in the editor: the field key, on the open card (or the client page). */
  doc?: string;
}

const firstBoard = () => BOARDS[0].table;
const isBoard = (t?: string) => !!t && BOARDS.some((b) => b.table === t);

export function parse(path: string, search: string): Route {
  const parts = path.split('/').filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
  const params = new URLSearchParams(search || '');
  let route: Route = { screen: 'home' };
  switch (parts[0]) {
    case 'dashboard': route = { screen: 'dashboard' }; break;
    case 'tasks': route = { screen: 'tasks', board: isBoard(parts[1]) ? parts[1] : firstBoard() }; break;
    case 'board':
      route = { screen: 'tasks', board: isBoard(parts[1]) ? parts[1] : firstBoard() };
      if (parts[1] && parts[2]) route.card = { table: parts[1], id: parts[2] };
      break;
    case 'clients': route = parts[1] ? { screen: 'client', id: parts[1] } : { screen: 'clients' }; break;
    case 'team': route = parts[1] ? { screen: 'member', id: parts[1] } : { screen: 'team' }; break;
    case 'forms': route = { screen: 'forms', id: parts[1] }; break;
    default: route = { screen: 'home' };
  }
  const card = params.get('card');
  if (card && card.indexOf(':') > 0 && !route.card) {
    const at = card.indexOf(':');
    route.card = { table: card.slice(0, at), id: card.slice(at + 1) };
  }
  const doc = params.get('doc');
  if (doc && (route.card || route.screen === 'client')) route.doc = doc;
  return route;
}

/** The link for a route. */
export function href(r: Route): string {
  const e = encodeURIComponent;
  let path = '/';
  let cardInPath = false;
  switch (r.screen) {
    case 'tasks':
      if (r.card && isBoard(r.card.table) && r.card.table === (r.board || firstBoard())) {
        path = '/board/' + e(r.card.table) + '/' + e(r.card.id); cardInPath = true;
      } else path = '/tasks' + (r.board && r.board !== firstBoard() ? '/' + e(r.board) : '');
      break;
    case 'dashboard': path = '/dashboard'; break;
    case 'clients': path = '/clients'; break;
    case 'client': path = '/clients/' + e(r.id || ''); break;
    case 'team': path = '/team'; break;
    case 'member': path = '/team/' + e(r.id || ''); break;
    case 'forms': path = '/forms' + (r.id ? '/' + e(r.id) : ''); break;
    default: path = '/';
  }
  const q: string[] = [];
  if (r.card && !cardInPath) q.push('card=' + e(r.card.table + ':' + r.card.id));
  if (r.doc && (r.card || r.screen === 'client')) q.push('doc=' + e(r.doc));
  return path + (q.length ? '?' + q.join('&') : '');
}

/* ---------- the current route --------------------------------------------- */

const here = () => (typeof location === 'undefined' ? '/' : location.pathname + location.search);
let current: Route = typeof location === 'undefined' ? { screen: 'home' } : parse(location.pathname, location.search);
const subs = new Set<() => void>();
/** The addresses visited before this one, for the record pages' back button. */
const trail: string[] = [];
let currentPath = here();

function changed() {
  currentPath = here();
  current = parse(location.pathname, location.search);
  subs.forEach((f) => f());
}

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    if (trail.length && trail[trail.length - 1] === here()) trail.pop();
    changed();
  });
}

/** The current route; re-renders on navigation. */
export function useRoute(): Route {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => current, () => current);
}
export function getRoute(): Route { return current; }

/** Go somewhere. `replace` swaps the history entry instead of adding one. */
export function navigate(r: Route | string, replace = false): void {
  const to = typeof r === 'string' ? r : href(r);
  if (to === here()) return;
  if (replace) history.replaceState(null, '', to);
  else { trail.push(currentPath); history.pushState(null, '', to); }
  changed();
}

/** Where the back button goes (null when nothing came before). */
export function previous(): Route | null {
  if (!trail.length) return null;
  const p = trail[trail.length - 1];
  const q = p.indexOf('?');
  return parse(q > -1 ? p.slice(0, q) : p, q > -1 ? p.slice(q) : '');
}
/** Back one step (to `fallback` when there is no history). */
export function back(fallback: Route): void {
  if (trail.length) history.back();
  else navigate(fallback);
}

/** Open a card over the current screen (or, on Tasks, over its own board). */
export function openCard(table: string, id: string): void {
  const r = getRoute();
  if (r.screen === 'tasks' && isBoard(table)) navigate({ screen: 'tasks', board: table, card: { table, id } });
  else navigate({ ...r, card: { table, id }, doc: undefined });
}
/** Close the open card. */
export function closeCard(): void {
  const r = getRoute();
  navigate({ ...r, card: undefined, doc: undefined });
}

/** Open a copy document in the editor (over the open card, or the client page). */
export function openDoc(field: string): void {
  navigate({ ...getRoute(), doc: field });
}
/** Close the editor. */
export function closeDoc(): void {
  navigate({ ...getRoute(), doc: undefined });
}

/** A plain left click (not a new tab): let the app move instead of the browser. */
export function inApp(e: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean; preventDefault(): void }, to: Route | string): void {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  navigate(to);
}
