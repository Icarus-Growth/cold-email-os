/* Which component draws each screen, the card panel over it, and the copy editor over both. */
import React from 'react';
import type { Route } from '../lib/router';
import { Dashboard } from '../areas/dashboard';
import { Home } from '../areas/home';
import { TasksScreen } from '../areas/tasks';
import { ClientPage, ClientsTable } from '../areas/clients';
import { MemberPage, TeamTable } from '../areas/team';
import { FormsTable } from '../areas/forms';
import { CardPanel } from '../areas/records/CardPanel';

/** The page body for a route. */
export function screenFor(r: Route): React.ReactNode {
  switch (r.screen) {
    case 'dashboard': return <Dashboard />;
    case 'tasks': return <TasksScreen />;
    case 'clients': return <ClientsTable />;
    case 'client': return <ClientPage key={r.id} id={r.id || ''} />;
    case 'team': return <TeamTable />;
    case 'member': return <MemberPage key={r.id} id={r.id || ''} />;
    case 'forms': return <FormsTable />;
    default: return <Home />;
  }
}

/** The card open over the page, if any. Keyed by id so each card starts at its top. */
export function panelFor(r: Route): React.ReactNode {
  return r.card ? <CardPanel key={r.card.table + r.card.id} table={r.card.table} id={r.card.id} /> : null;
}

/* The editor (Tiptap) loads the first time a document opens, so other pages stay small. */
const DocEditor = React.lazy(() => import('../areas/docs/DocEditor').then((m) => ({ default: m.DocEditor })));

/** The copy document open in the editor, if any (over the card, or over the client page). */
export function docFor(r: Route): React.ReactNode {
  return r.doc ? <React.Suspense fallback={null}><DocEditor r={r} /></React.Suspense> : null;
}
