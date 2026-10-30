import React, { useEffect, useRef, useState } from 'react';

/* Every editor here keeps its own draft while it has focus. A save, a live
 * update or a reload changes the `value` prop, but the box the person is
 * typing in is never overwritten: it takes the new value only once they have
 * left it. That is what keeps focus, caret and scroll where they are. */

const BOX = 'w-full rounded-[10px] border border-line bg-card px-3 text-[13px] text-ink placeholder:text-faint focus:outline-none focus:border-[var(--border-focus)] focus:ring-2 focus:ring-[var(--focus-ring)]';

function useDraft(value: string) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setDraft(value); }, [value]);
  return { draft, setDraft, focused };
}

export interface TextInputProps {
  value?: string | null;
  /** Called on blur or Enter, only when the text changed. */
  onSave: (v: string) => void;
  placeholder?: string;
  type?: 'text' | 'email' | 'url' | 'number' | 'date' | 'datetime-local';
  'aria-label'?: string;
  className?: string;
  /** The column it edits, rendered as data-field (tests and the live app find a box by it). */
  field?: string;
}

/** A one-line text box that saves when the person clicks away (or presses Enter). */
export function TextInput({ value, onSave, placeholder, type = 'text', className = '', field, ...rest }: TextInputProps) {
  const v = value === null || value === undefined ? '' : String(value);
  const { draft, setDraft, focused } = useDraft(v);
  const commit = () => { if (draft !== v) onSave(draft); };
  return (
    <input type={type} className={`${BOX} h-[34px] ${className}`} value={draft} placeholder={placeholder}
      aria-label={rest['aria-label']} data-field={field}
      onFocus={() => { focused.current = true; }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { focused.current = false; commit(); }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
      onClick={(e) => e.stopPropagation()} />
  );
}

/** A plain multi-line box (call scripts, template text) that saves when the person clicks away. */
export function TextArea({ value, onSave, placeholder, rows = 5, className = '', field, ...rest }: {
  value?: string | null; onSave: (v: string) => void; placeholder?: string; rows?: number; className?: string; 'aria-label'?: string;
  /** The column it edits, rendered as data-field. */
  field?: string;
}) {
  const v = value === null || value === undefined ? '' : String(value);
  const { draft, setDraft, focused } = useDraft(v);
  return (
    <textarea className={`${BOX} py-2 leading-[20px] resize-y min-h-[88px] ${className}`} rows={rows} value={draft}
      placeholder={placeholder} aria-label={rest['aria-label']} data-field={field}
      onFocus={() => { focused.current = true; }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { focused.current = false; if (draft !== v) onSave(draft); }} />
  );
}

/** A checkbox that saves the moment it changes. */
export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: React.ReactNode }) {
  return (
    <label className="inline-flex items-center gap-2 text-[13px] text-ink2 cursor-pointer" onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" className="w-4 h-4 accent-[var(--button-primary-bg)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** A dropdown. `large` is the big single select doctrine asks for on a record's main status. */
export function Select({ value, options, onChange, placeholder, large, className = '', ...rest }: {
  value: string; options: Array<[string, string]>; onChange: (v: string) => void; placeholder?: string;
  large?: boolean; className?: string; 'aria-label'?: string;
}) {
  return (
    <select className={`${BOX} ${large ? 'h-[40px] text-[14px] font-semibold bg-ground' : 'h-[34px]'} pr-8 ${className}`}
      value={value} aria-label={rest['aria-label']} onChange={(e) => onChange(e.target.value)} onClick={(e) => e.stopPropagation()}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}
