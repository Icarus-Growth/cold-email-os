import React from 'react';
import { X } from 'lucide-react';
import { IconButton } from './Button';
import { dismissToast, toasts } from '../lib/ui';
import { useEscapeLayer, type EscapeLayer } from './escape';

/** A centred dialog over a dim page. Escape or a click outside closes it. `footer` holds its buttons.
 *  `layer` sets where it sits in the Escape order: 'confirm' (the confirm box), 'drill' (a drill list), 'modal'. */
export function Modal({ title, onClose, children, footer, wide, role = 'dialog', layer = 'modal' }: {
  title: React.ReactNode; onClose: () => void; children?: React.ReactNode; footer?: React.ReactNode;
  wide?: boolean; role?: 'dialog' | 'alertdialog'; layer?: Extract<EscapeLayer, 'confirm' | 'drill' | 'modal'>;
}) {
  useEscapeLayer(layer, onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[var(--overlay)]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role={role} aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}
        className={`w-full ${wide ? 'max-w-[760px]' : 'max-w-[480px]'} max-h-[calc(100vh-32px)] flex flex-col rounded-[14px] bg-card border border-line shadow-[var(--shadow-xl)]`}>
        <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b border-line2">
          <h2 className="font-display text-[18px] font-semibold text-ink flex-1 min-w-0">{title}</h2>
          <IconButton icon={X} label="Close" onClick={onClose} />
        </div>
        <div className="px-5 py-4 overflow-y-auto flex-1" data-scroll>{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line2 flex items-center gap-2 flex-wrap">{footer}</div>}
      </div>
    </div>
  );
}

/** A slide-out from the right (the Knowledge base). Escape or the dim area closes it. */
export function Drawer({ title, onClose, children }: { title: React.ReactNode; onClose: () => void; children?: React.ReactNode }) {
  useEscapeLayer('drawer', onClose);
  return (
    <>
      <button type="button" aria-label="Close" className="fixed inset-0 z-40 bg-[var(--overlay-light)] cursor-default" onClick={onClose} />
      <aside role="dialog" aria-label={typeof title === 'string' ? title : 'Drawer'} data-drawer
        className="fixed z-50 top-0 right-0 bottom-0 w-[min(720px,100vw)] bg-card border-l border-line shadow-[var(--shadow-xl)] flex flex-col">
        <div className="flex items-center gap-3 px-5 h-[60px] border-b border-line2 shrink-0">
          <h2 className="font-display text-[18px] font-semibold text-ink flex-1">{title}</h2>
          <IconButton icon={X} label="Close" onClick={onClose} />
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4" data-scroll>{children}</div>
      </aside>
    </>
  );
}

/** Where toasts appear (the shell mounts this once). Use toast() from lib/ui to show one. */
export function ToastHost() {
  const list = toasts.use();
  if (!list.length) return null;
  return (
    <div className="fixed z-[60] bottom-4 left-1/2 -translate-x-1/2 flex flex-col gap-2 w-[min(520px,calc(100vw-32px))]" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} role={t.tone === 'bad' ? 'alert' : 'status'}
          className={`flex items-start gap-3 rounded-[12px] px-4 py-2.5 text-[13px] shadow-[var(--shadow-lg)] border ${
            t.tone === 'bad' ? 'bg-[#fdf1f1] border-[#f3c9c9] text-bad' : t.tone === 'good' ? 'bg-[#eef8f1] border-[#c6e8d1] text-[var(--text-success)]' : 'bg-card border-line text-ink'}`}>
          <span className="flex-1 min-w-0 break-words">{t.text}</span>
          <button type="button" aria-label="Dismiss" className="shrink-0 opacity-70 hover:opacity-100" onClick={() => dismissToast(t.id)}><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}
