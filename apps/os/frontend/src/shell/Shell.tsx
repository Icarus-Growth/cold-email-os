/* The app shell: side menu, page header, the page, the card panel, and the overlays
 * ("New X" form, confirm box, toasts). Screens draw only the page body. */
import React from 'react';
import { ArrowLeft, Menu, Plus, UserPlus, X } from 'lucide-react';
import { useData, useSaving } from '../lib/store';
import { back, inApp, previous, useRoute, type Route } from '../lib/router';
import { confirmBox, createOpen, navOpen, screenFilters } from '../lib/ui';
import { AGENCY, BOARDS } from '../lib/schema';
import * as Auth from '../lib/auth';
import { Button, IconButton, Modal, ToastHost } from '../ui';
import { useEscapeLayer } from '../ui/escape';
import { BOARD_PAGE, DESC, NAV, RECORD_PAGE, headTitle, navCount, navFor } from './nav';
import { docFor, panelFor, screenFor } from './routes';
import { CreateModal } from './CreateModal';
import { Mark } from './Mark';
import { AreaBoundary } from './AreaBoundary';

function Sidebar() {
  const S = useData();
  const r = useRoute();
  const f = screenFilters.use();
  const lit = navFor(r.screen);
  return (
    <aside data-sidebar className="w-[232px] shrink-0 h-full flex flex-col bg-card border-r border-line">
      <div className="h-[60px] px-5 flex items-center gap-2.5 shrink-0">
        <Mark size={26} radius={7} />
        <div className="leading-tight min-w-0">
          <div className="font-display font-semibold text-[15px] text-ink truncate">{S.agencyName} OS</div>
          <div className="text-[11px] text-muted -mt-0.5">{AGENCY.agency}</div>
        </div>
      </div>
      <nav className="flex-1 min-h-0 px-3 pt-2 overflow-y-auto overscroll-contain" aria-label="Main">
        {NAV.map(([id, label, Icon]) => {
          const on = id === lit;
          const to = id === 'home' ? '/' : '/' + id;
          const count = navCount(S, id, f);
          return (
            <a key={id} href={to} aria-current={on ? 'page' : undefined} data-nav={id}
              onClick={(e) => { navOpen.set(false); inApp(e, to); }}
              className={`w-full flex items-center gap-2.5 h-[34px] px-2.5 mb-0.5 rounded-[8px] text-[13.5px] no-underline ${on ? 'bg-taccent text-ink font-semibold' : 'text-ink2 hover:bg-ground'}`}>
              <Icon size={16} strokeWidth={on ? 2.2 : 1.8} className={on ? 'text-ink' : 'text-muted'} />
              <span className="flex-1 truncate">{label}</span>
              {count !== null && <span className="text-[12px] text-muted tnum">{count}</span>}
            </a>
          );
        })}
      </nav>
      <div className="p-3 border-t border-line2 shrink-0 bg-card" style={{ paddingBottom: 'calc(12px + env(safe-area-inset-bottom, 0px))' }}>
        <div className="px-2 text-[11.5px] text-muted">The page reads the database again every minute.</div>
        <div className="flex items-center gap-2 px-2 mt-2">
          <span className="text-[12px] text-ink2 truncate flex-1 min-w-0" title={Auth.email()}>{S.me ? S.me.full_name : Auth.email()}</span>
          <Button size="sm" variant="ghost" onClick={Auth.signOut}>Sign out</Button>
        </div>
      </div>
    </aside>
  );
}

/** The header's one button for a screen (null for none). */
function headAction(S: ReturnType<typeof useData>, r: Route): { label: string; icon: typeof Plus; run: () => void } | null {
  if (r.screen === 'tasks') {
    const def = BOARDS.find((b) => b.table === r.board) || BOARDS[0];
    return { label: 'New ' + def.item, icon: Plus, run: () => createOpen.set({ table: def.table }) };
  }
  if (r.screen === 'clients') return { label: 'New client', icon: Plus, run: () => createOpen.set({ table: 'clients' }) };
  if (r.screen === 'team' && S.isAdmin) return { label: 'Add team member', icon: UserPlus, run: () => createOpen.set({ table: 'team' }) };
  return null;
}

function PageHeader() {
  const S = useData();
  const r = useRoute();
  const saving = useSaving();
  const isRecord = RECORD_PAGE.indexOf(r.screen) > -1;
  const prev = previous();
  const desc = DESC[r.screen];
  const action = headAction(S, r);
  const fallback: Route = { screen: navFor(r.screen) };
  return (
    <div className="flex items-start gap-4 flex-wrap pb-4" data-page-header>
      <div className="flex items-start gap-2 min-w-0 flex-1">
        {isRecord && (
          <IconButton icon={ArrowLeft} className="mt-[5px] shrink-0"
            label={'Back to ' + headTitle(S, prev || fallback)} onClick={() => back(fallback)} />
        )}
        <div className="min-w-0">
          <h1 className="font-display text-[28px] leading-[36px] font-semibold text-ink break-words max-[720px]:text-[22px] max-[720px]:leading-[30px]">{headTitle(S, r)}</h1>
          {desc && <p className="text-[14px] text-muted italic mt-1"><span className="not-italic mr-1">{desc[0]}</span>{desc[1]}</p>}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {saving > 0 && <span className="text-[12.5px] text-muted" role="status" data-saving>Saving…</span>}
        {action && <Button variant="outline" icon={action.icon} onClick={action.run} data-head-action>{action.label}</Button>}
      </div>
    </div>
  );
}

function PhoneBar() {
  const S = useData();
  const r = useRoute();
  const open = navOpen.use();
  return (
    <div className="hidden max-[900px]:flex items-center gap-2 h-[52px] px-4 bg-card border-b border-line shrink-0" data-topbar>
      <Button size="sm" icon={open ? X : Menu} aria-expanded={open} onClick={() => navOpen.set(!open)}>{open ? 'Close' : 'Menu'}</Button>
      <span className="flex-1 min-w-0 truncate text-[14px] font-medium text-ink text-center">{headTitle(S, r)}</span>
      <span className="w-[72px]" />
    </div>
  );
}

function ConfirmHost() {
  const c = confirmBox.use();
  if (!c) return null;
  const close = () => confirmBox.set(null);
  return (
    <Modal role="alertdialog" layer="confirm" title={c.title} onClose={close} footer={<>
      <Button variant="danger" id="os-confirm-go" onClick={() => { const run = c.run; close(); run(); }}>{c.verb}</Button>
      <Button onClick={close}>Cancel</Button>
    </>}>
      <p className="text-[13.5px] text-ink2 leading-[21px]">{c.body}</p>
    </Modal>
  );
}

export function Shell() {
  const r = useRoute();
  const open = navOpen.use();
  // Escape shuts the phone menu (after any confirm box or drill list; before a form or the panel).
  useEscapeLayer('menu', () => navOpen.set(false), open);
  const board = BOARD_PAGE.indexOf(r.screen) > -1;
  const pageKey = r.screen + ':' + (r.id || '') + ':' + (r.board || '');
  const S = useData();
  const name = headTitle(S, r);
  React.useEffect(() => { document.title = name + ' · OS'; }, [name]);
  return (
    <div className="h-full flex font-sans bg-ground" data-screen={r.screen}>
      {/* Desktop: a fixed column. Phone: slides in over the page. */}
      <div className={`h-full max-[900px]:fixed max-[900px]:z-50 max-[900px]:top-0 max-[900px]:bottom-0 max-[900px]:h-[100dvh] max-[900px]:left-0 max-[900px]:transition-transform ${open ? 'max-[900px]:shadow-[var(--shadow-xl)]' : 'max-[900px]:-translate-x-full'}`}>
        <Sidebar />
      </div>
      {open && <button type="button" aria-label="Close the menu" className="hidden max-[900px]:block fixed inset-0 z-40 bg-[var(--overlay-light)]" onClick={() => navOpen.set(false)} />}
      <main className="flex-1 min-w-0 h-full flex flex-col">
        <PhoneBar />
        {board ? (
          <div className="flex-1 min-h-0 flex flex-col px-10 pt-5 pb-3 max-[720px]:px-4 max-[720px]:pt-4">
            <PageHeader />
            <div className="flex-1 min-h-0 flex flex-col" data-page>
              <AreaBoundary key={pageKey} name={name}>{screenFor(r)}</AreaBoundary>
            </div>
          </div>
        ) : (
          <div key={pageKey} className="flex-1 min-h-0 overflow-y-auto px-10 pt-5 pb-10 max-[720px]:px-4 max-[720px]:pt-4" data-scroll>
            <PageHeader />
            <div data-page><AreaBoundary name={name}>{screenFor(r)}</AreaBoundary></div>
          </div>
        )}
      </main>
      {r.card && <AreaBoundary key={r.card.table + r.card.id} name="This card">{panelFor(r)}</AreaBoundary>}
      {r.doc && <AreaBoundary key={'doc:' + (r.card ? r.card.table + r.card.id : r.id) + ':' + r.doc} name="This document">{docFor(r)}</AreaBoundary>}
      <CreateModal />
      <ConfirmHost />
      <ToastHost />
    </div>
  );
}
