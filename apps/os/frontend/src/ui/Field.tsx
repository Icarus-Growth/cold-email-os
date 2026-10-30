import React from 'react';
import { LinkButton } from './Button';

export type ValueTone = 'good' | 'warn' | 'bad' | 'mute' | null | undefined;

const TONE: Record<string, string> = { good: 'text-good', warn: 'text-warn', bad: 'text-bad', mute: 'text-muted' };

/** One field on a record: the name on the left (with an optional description under it), the value on the right. */
export function FieldRow({ label, desc, children }: { label: string; desc?: string | null; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(96px,28%)_1fr] gap-3 items-start min-h-[28px] text-[13px] max-[520px]:grid-cols-1 max-[520px]:gap-1">
      <div className="pt-[5px] min-w-0">
        <div className="text-muted text-[12.5px]">{label}</div>
        {desc && <div className="text-faint text-[11.5px] italic leading-[15px] mt-0.5">{desc}</div>}
      </div>
      <div className="min-w-0 pt-[3px]">{children}</div>
    </div>
  );
}

/** A read-only value, optionally toned (good/warn/bad/mute). Keeps line breaks. */
export function FieldValue({ children, tone }: { children: React.ReactNode; tone?: ValueTone }) {
  return <div className={`text-ink whitespace-pre-line break-words leading-[20px] ${tone ? TONE[tone] : ''}`}>{children}</div>;
}

/** A value that opens something inside the OS (a client, a linked record). */
export function FieldLink({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="text-left text-ink2 underline decoration-[var(--border-primary_hover)] underline-offset-2 hover:text-ink">
      {children}
    </button>
  );
}

/** Every link in the app: the full address (readable, copyable) with an "Open document" button beside it. */
export function LinkRow({ url, label = 'Open document', extra }: { url: string; label?: string; extra?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <a href={url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
        className="min-w-0 truncate text-ink2 underline decoration-[var(--border-primary_hover)] underline-offset-2 text-[12.5px]">{url}</a>
      <LinkButton href={url} className="shrink-0">{label}</LinkButton>
      {extra}
    </div>
  );
}

/** A field as data — the same shape the live app's sections use, so ported screens map one to one.
 *  k = label · v = text value · node = any control instead · go = makes v a link inside the OS · tone · desc. */
export interface FieldSpec {
  k: string;
  v?: React.ReactNode;
  node?: React.ReactNode;
  desc?: string | null;
  tone?: ValueTone;
  go?: () => void;
}

/** Render one FieldSpec as a FieldRow. */
export function Field({ f }: { f: FieldSpec }) {
  const value = f.go ? <FieldLink onClick={f.go}>{f.v}</FieldLink>
    : f.node !== undefined ? f.node
    : <FieldValue tone={f.tone}>{f.v === undefined || f.v === null || f.v === '' ? '—' : f.v}</FieldValue>;
  return <FieldRow label={f.k} desc={f.desc}>{value}</FieldRow>;
}

/** A field for a URL column: the link + button, or "Not set". */
export function linkField(k: string, url?: string | null, desc?: string | null, label?: string): FieldSpec {
  return url ? { k, desc, v: url, node: <LinkRow url={url} label={label} /> } : { k, desc, v: 'Not set', tone: 'mute' };
}
