import React from 'react';
import { initials, shortStage, stageNumber } from '../lib/format';

export type TagTone = 'good' | 'warn' | 'bad' | 'grey' | 'accent';

const TONE: Record<TagTone, string> = {
  good: 'bg-tgood text-[var(--text-success)]',
  warn: 'bg-twarn text-warn',
  bad: 'bg-tbad text-bad',
  grey: 'bg-chrome text-ink2',
  accent: 'bg-taccent text-ink2',
};

/** A small rounded status pill. Status colours are never the brand colour. */
export function Tag({ tone = 'grey', children, className = '' }: { tone?: TagTone; children: React.ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1 h-[22px] px-2 rounded-full text-[12px] font-medium whitespace-nowrap ${TONE[tone]} ${className}`}>{children}</span>;
}

/** The tone of a stage: 100 is green, a stage below 0 (Rejected) is red, a number ending in 9
 *  (the work is held: sent back or blocked) is amber, everything else grey. */
export function stageTone(stage?: string | null): TagTone {
  const n = stageNumber(stage);
  if (n === null) return 'grey';
  if (n === 100) return 'good';
  if (n < 0) return 'bad';
  if (n % 10 === 9) return 'warn';
  return 'grey';
}

/** A stage as a pill with its ladder glyph. Shows the stage name without its number; the full name is the tooltip. */
export function StagePill({ stage, ladder, full = false }: { stage: string; ladder?: readonly string[]; full?: boolean }) {
  return (
    <Tag tone={stageTone(stage)}>
      {ladder && <StageGlyph stage={stage} ladder={ladder} size={12} />}
      <span title={stage}>{full ? stage : shortStage(stage)}</span>
    </Tag>
  );
}

/** A coloured square or dot (a client's chart colour). */
export function Dot({ colour, size = 8, square = true }: { colour: string; size?: number; square?: boolean }) {
  return <span aria-hidden className="inline-block shrink-0" style={{ width: size, height: size, borderRadius: square ? 2 : 99, background: colour }} />;
}

/** Initials in a circle. "Unassigned" / empty shows a grey "?". */
export function Avatar({ name, size = 20 }: { name?: string | null; size?: number }) {
  const none = !name || name === 'Unassigned';
  return (
    <span aria-hidden className="inline-flex items-center justify-center rounded-full shrink-0 font-semibold"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42),
        background: none ? 'var(--bg-tertiary)' : 'var(--tint-accent)', color: none ? 'var(--text-placeholder)' : 'var(--text-secondary)' }}>
      {none ? '?' : initials(name)}
    </span>
  );
}

/** Where a card is on its ladder: dashed ring = first stage, a pie that fills, a green check = done. */
export function StageGlyph({ stage, ladder, size = 14 }: { stage: string; ladder: readonly string[]; size?: number }) {
  const i = ladder.indexOf(stage), n = ladder.length - 1;
  const r = size / 2 - 1.5, c = size / 2;
  if (i <= 0) return <svg aria-hidden width={size} height={size} className="shrink-0"><circle cx={c} cy={c} r={r} fill="none" stroke="var(--text-placeholder)" strokeWidth={1.5} strokeDasharray="2 2" /></svg>;
  if (i === n) return (
    <svg aria-hidden width={size} height={size} className="shrink-0"><circle cx={c} cy={c} r={r + 0.5} fill="var(--good)" />
      <path d={`M${c - r * 0.45},${c} l${r * 0.35},${r * 0.35} l${r * 0.6},${-r * 0.7}`} stroke="#ffffff" strokeWidth={1.6} fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
  );
  const f = i / n, a = f * 2 * Math.PI, ir = r - 2;
  const x = c + ir * Math.sin(a), y = c - ir * Math.cos(a);
  return (
    <svg aria-hidden width={size} height={size} className="shrink-0">
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--text-secondary)" strokeWidth={1.5} />
      <path d={`M${c},${c} L${c},${c - ir} A${ir},${ir} 0 ${f > 0.5 ? 1 : 0} 1 ${x},${y} Z`} fill="var(--text-secondary)" />
    </svg>
  );
}
