import React, { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronRight } from 'lucide-react';
import { Field, type FieldSpec } from './Field';
import { Button } from './Button';

/** A section's top-right button. On a stage group it moves the card to the next stage. */
export interface SectionButton {
  label: string;
  onClick: () => void;
  /** One line under the button saying what pressing it sets off (doctrine: buttons that trigger something carry a warning). */
  warn?: string;
  disabled?: boolean;
  /** Filled with the brand colour. Defaults to true for the current stage, false elsewhere. */
  primary?: boolean;
}

/** One section of a record (a stage group, Basic Details, Links, For Devs Only…). */
export interface SectionSpec {
  title: string;
  /** Italic line under the title: who it is for and what they do here. */
  desc?: string | null;
  /** meta = not a stage (Basic Details etc.) · done = a stage already passed (folds to one line) ·
   *  current = the stage the record is in (highlighted, filled button) · todo = a later stage. */
  state?: 'meta' | 'done' | 'current' | 'todo';
  button?: SectionButton | null;
  /** The section folds open and closed from its title (a meta section only). The choice is kept per browser
   *  under `foldKey` (default: the title). */
  fold?: boolean;
  foldKey?: string;
  /** With `fold`: start closed until the person opens it. */
  closed?: boolean;
  fields?: FieldSpec[];
  /** Anything else under the fields. */
  children?: React.ReactNode;
}

function foldRead(key: string, fallback: boolean): boolean {
  try { const v = window.localStorage.getItem('os-fold:' + key); return v === null ? fallback : v === '1'; }
  catch { return fallback; }
}
function foldWrite(key: string, open: boolean) {
  try { window.localStorage.setItem('os-fold:' + key, open ? '1' : '0'); } catch { /* private window: not kept */ }
}

/** A meta section that folds open and closed from its title. */
function FoldSection({ s, hasBody }: { s: SectionSpec; hasBody: boolean }) {
  const key = s.foldKey || s.title;
  const [open, setOpenState] = useState(() => foldRead(key, !s.closed));
  const setOpen = (v: boolean) => { setOpenState(v); foldWrite(key, v); };
  const btn = s.button;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section data-section={s.title} data-open={open ? 'true' : 'false'}>
      <div className="flex items-start gap-3">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open ? 'true' : 'false'}
          className="min-w-0 flex-1 text-left group">
          <h3 className="text-[14px] font-semibold text-ink flex items-center gap-1.5 flex-wrap">
            <Chevron size={15} className="text-muted group-hover:text-ink shrink-0 -ml-0.5" />{s.title}
          </h3>
          {s.desc && <p className="text-[12.5px] text-muted italic leading-[17px] mt-0.5 pl-[20px]">{s.desc}</p>}
        </button>
        {btn && open && (
          <Button size="sm" variant={btn.primary ? 'primary' : 'secondary'} disabled={btn.disabled} onClick={btn.onClick}>{btn.label}</Button>
        )}
      </div>
      {open && btn && btn.warn && (
        <div className="mt-1.5 text-[11.5px] text-warn inline-flex items-center gap-1"><AlertTriangle size={11} />{btn.warn}</div>
      )}
      {open && hasBody && (
        <div className="mt-2.5 space-y-1.5">
          {(s.fields || []).map((f, i) => <Field key={f.k + ':' + i} f={f} />)}
          {s.children}
        </div>
      )}
    </section>
  );
}

/** Render one record section (H's look). A done stage folds to a single line that opens on click;
 *  a meta section with `fold` folds open and closed from its title. */
export function Section({ s }: { s: SectionSpec }) {
  const state = s.state || 'meta';
  const [open, setOpen] = useState(false);
  const hasBody = !!((s.fields && s.fields.length) || s.children);
  if (s.fold && state === 'meta') return <FoldSection s={s} hasBody={hasBody} />;

  if (state === 'done' && !open) {
    return (
      <div className="flex items-start gap-2 text-[12.5px]">
        <span className="inline-flex items-center justify-center w-[16px] h-[16px] mt-[2px] rounded-full bg-good text-white shrink-0"><Check size={10} strokeWidth={3} /></span>
        <div className="min-w-0 flex-1"><span className="font-medium text-ink2">{s.title}</span> {s.desc && <span className="text-faint italic">{s.desc}</span>}</div>
        {hasBody && (
          <button type="button" onClick={() => setOpen(true)} aria-expanded="false" aria-label={'Show ' + s.title}
            className="shrink-0 inline-flex items-center gap-0.5 text-[11.5px] text-muted hover:text-ink">Show<ChevronRight size={12} /></button>
        )}
      </div>
    );
  }

  const cur = state === 'current';
  const btn = s.button;
  const primary = btn ? (btn.primary ?? cur) : false;
  return (
    <section className={cur ? 'rounded-[12px] bg-ground p-3 -mx-1 border border-line' : ''} data-section={s.title}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-semibold text-ink flex items-center gap-2 flex-wrap">
            {state === 'done' && <span className="inline-flex items-center justify-center w-[16px] h-[16px] rounded-full bg-good text-white"><Check size={10} strokeWidth={3} /></span>}
            {s.title}
            {cur && <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-keybg text-ink2">Current stage</span>}
          </h3>
          {s.desc && <p className="text-[12.5px] text-muted italic leading-[17px] mt-0.5">{s.desc}</p>}
        </div>
        {btn && (
          <Button size="sm" variant={primary ? 'primary' : 'secondary'} disabled={btn.disabled} onClick={btn.onClick}
            className={!primary && state === 'todo' ? 'text-faint' : ''}>{btn.label}</Button>
        )}
        {state === 'done' && (
          <button type="button" onClick={() => setOpen(false)} aria-expanded="true" aria-label={'Hide ' + s.title}
            className="shrink-0 inline-flex items-center gap-0.5 text-[11.5px] text-muted hover:text-ink">Hide<ChevronDown size={12} /></button>
        )}
      </div>
      {cur && btn && btn.warn && (
        <div className="mt-1.5 text-[11.5px] text-warn inline-flex items-center gap-1"><AlertTriangle size={11} />{btn.warn}</div>
      )}
      {hasBody && (
        <div className="mt-2.5 space-y-1.5">
          {(s.fields || []).map((f, i) => <Field key={f.k + ':' + i} f={f} />)}
          {s.children}
        </div>
      )}
    </section>
  );
}

/** A list of sections with even spacing. Null entries are skipped. */
export function Sections({ sections }: { sections: Array<SectionSpec | null | undefined | false> }) {
  return (
    <div className="space-y-5">
      {sections.filter(Boolean).map((s, i) => <Section key={(s as SectionSpec).title + ':' + i} s={s as SectionSpec} />)}
    </div>
  );
}

/** A soft white card (dashboards, tables, page blocks). */
export function Card({ children, className = '', ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-[14px] bg-card border border-line shadow-[var(--shadow-sm)] ${className}`} {...rest}>{children}</div>;
}

/** A card with a title, an optional italic description and an optional right-hand slot. */
export function CardHeader({ title, desc, right }: { title: React.ReactNode; desc?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="px-5 pt-3.5 pb-2 flex items-start gap-3">
      <div className="min-w-0">
        <h3 className="text-[14.5px] font-semibold text-ink">{title}</h3>
        {desc && <p className="text-[12.5px] text-muted italic">{desc}</p>}
      </div>
      {right && <div className="ml-auto shrink-0 flex items-center gap-2">{right}</div>}
    </div>
  );
}
