import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

/** A pill-shaped single choice from plain words: "Status  Active ⌄". The first option is the default;
 *  any other choice tints the pill. (The Team and Clients Status filters, Group by, Sort, View as.) */
export function ChoicePill({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  const on = value !== options[0];
  return (
    <label className={`relative h-[32px] pl-3 pr-7 rounded-full border text-[13px] inline-flex items-center gap-1.5 whitespace-nowrap cursor-pointer hover:border-[var(--border-primary_hover)] ${on ? 'bg-taccent border-[var(--border-brand)]' : 'bg-card border-line'}`}
      data-choice={label}>
      <span className="text-muted">{label}</span>
      <span className="text-ink font-medium max-w-[180px] truncate">{value}</span>
      <ChevronDown size={13} className="text-faint absolute right-2.5" />
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 opacity-0 cursor-pointer w-full">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

/** A pill that picks several: "Client  2 selected ⌄", ticks in a list underneath. Empty = all. */
export function MultiPill({ label, values, options, onToggle }: {
  label: string; values: string[]; options: string[]; onToggle: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); } };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc, true);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc, true); };
  }, [open]);
  const shown = values.length === 0 ? 'All' : values.length === 1 ? values[0] : values.length + ' selected';
  return (
    <div ref={wrap} className="relative" data-filter={label}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className={`h-[32px] pl-3 pr-7 rounded-full border text-[13px] inline-flex items-center gap-1.5 whitespace-nowrap relative hover:border-[var(--border-primary_hover)] ${values.length ? 'bg-taccent border-[var(--border-brand)]' : 'bg-card border-line'}`}>
        <span className="text-muted">{label}</span>
        <span className="text-ink font-medium max-w-[180px] truncate">{shown}</span>
        <ChevronDown size={13} className="text-faint absolute right-2.5" />
      </button>
      {open && (
        <div role="listbox" aria-multiselectable="true"
          className="absolute z-30 left-0 top-[36px] w-[240px] max-h-[320px] overflow-y-auto rounded-[10px] bg-card border border-line shadow-[var(--shadow-lg)] py-1">
          {options.length ? options.map((o) => {
            const on = values.indexOf(o) > -1;
            return (
              <button key={o} type="button" role="option" aria-selected={on} onClick={() => onToggle(o)}
                className="flex items-center gap-2 w-full text-left px-3 py-1.5 text-[13px] text-ink2 hover:bg-ground">
                <span className={`inline-flex items-center justify-center w-[15px] h-[15px] rounded-[4px] border ${on ? 'bg-primary border-[var(--border-brand)] text-white' : 'border-line'}`}>
                  {on && <Check size={11} strokeWidth={3} />}
                </span>
                <span className="truncate">{o}</span>
              </button>
            );
          }) : <div className="px-3 py-2 text-[13px] text-faint">Nothing to filter on</div>}
        </div>
      )}
    </div>
  );
}

/** A pill-shaped dropdown: "Client  All clients ⌄" (A's look). */
export function FilterPill({ label, value, options, onChange, all }: {
  label: string; value: string; options: Array<[string, string]>; onChange: (v: string) => void; all: string;
}) {
  const shown = options.find((o) => o[0] === value);
  return (
    <label className="relative h-[32px] pl-3 pr-7 rounded-full bg-card border border-line text-[13px] inline-flex items-center gap-1.5 whitespace-nowrap cursor-pointer hover:border-[var(--border-primary_hover)]">
      <span className="text-muted">{label}</span>
      <span className="text-ink font-medium max-w-[180px] truncate">{shown ? shown[1] : all}</span>
      <ChevronDown size={13} className="text-faint absolute right-2.5" />
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 opacity-0 cursor-pointer w-full">
        <option value="">{all}</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

/** A date pill: "Created from  Any date". Empty, it says "Any date" (never the browser's dd/mm/yyyy);
 *  click it and the date box takes over. */
export function DatePill({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [focus, setFocus] = React.useState(false);
  const blank = !value && !focus;
  return (
    <label className="h-[32px] pl-3 pr-2 rounded-full bg-card border border-line text-[13px] inline-flex items-center gap-1.5 whitespace-nowrap cursor-pointer">
      <span className="text-muted">{label}</span>
      <span className="relative inline-flex items-center">
        <input type="date" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
          onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
          className={`font-medium bg-transparent text-[12.5px] focus:outline-none ${blank ? 'text-transparent' : 'text-ink'}`} />
        {blank && <span aria-hidden data-any-date className="absolute left-0 inset-y-0 flex items-center pointer-events-none text-ink font-medium text-[12.5px]">Any date</span>}
      </span>
    </label>
  );
}

/** "and" between filters. */
export function And() { return <span className="text-[11px] font-medium text-faint uppercase tracking-wide">and</span>; }
