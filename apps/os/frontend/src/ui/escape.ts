/* One Escape key for the whole app, closing the top layer only, in the live app's order
 * (web/js/app.js keydown): confirm box, drill list, Knowledge base drawer, phone menu,
 * "New X" form (any other modal), record panel. Each overlay registers itself with
 * useEscapeLayer(); the newest of two layers of the same kind wins. */
import { useEffect, useRef } from 'react';

export type EscapeLayer = 'confirm' | 'drill' | 'drawer' | 'menu' | 'modal' | 'panel';
const RANK: Record<EscapeLayer, number> = { confirm: 6, drill: 5, drawer: 4, menu: 3, modal: 2, panel: 1 };

interface Entry { kind: EscapeLayer; seq: number; close: () => void }
const layers = new Set<Entry>();
let seq = 0;
let installed = false;

function isTextBox(a: Element | null): a is HTMLElement {
  return !!a && ((a as HTMLElement).isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
}

function onKey(e: KeyboardEvent) {
  // Bubble phase: a box that handles Escape itself (the rich-text link box) stops it first.
  if (e.key !== 'Escape' || e.defaultPrevented || !layers.size) return;
  let top: Entry | null = null;
  layers.forEach((l) => { if (!top || RANK[l.kind] > RANK[top.kind] || (RANK[l.kind] === RANK[top.kind] && l.seq > top.seq)) top = l; });
  if (!top) return;
  const t = top as Entry;
  // Escape inside a text box on the record leaves the box, not the record.
  if (t.kind === 'panel' && isTextBox(document.activeElement)) { (document.activeElement as HTMLElement).blur(); e.preventDefault(); return; }
  e.preventDefault();
  t.close();
}

/** Register an overlay that Escape closes. `active` false = not open (e.g. the phone menu shut). */
export function useEscapeLayer(kind: EscapeLayer, close: () => void, active = true): void {
  const ref = useRef(close);
  ref.current = close;
  useEffect(() => {
    if (!active) return;
    if (!installed) { document.addEventListener('keydown', onKey); installed = true; }
    const entry: Entry = { kind, seq: ++seq, close: () => ref.current() };
    layers.add(entry);
    return () => { layers.delete(entry); };
  }, [kind, active]);
}
