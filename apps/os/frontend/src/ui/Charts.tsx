import React from 'react';
import { AlertTriangle, ArrowUpRight, Check } from 'lucide-react';
import { Dot } from './Tag';

/* ---------- scorecards --------------------------------------------------- */

export interface ScoreSpec {
  label: string;
  value: React.ReactNode;
  /** Small line under the number (the threshold breach, "Last 30 days"…). */
  note?: React.ReactNode;
  /** Set ONLY when the number is tied to a decision with an agreed threshold: good = green, bad = red. */
  tone?: 'good' | 'bad' | null;
  /** One of the most important cards: gets the tinted background. */
  key?: boolean;
}

/** One scorecard. Use inside ScoreGrid. */
export function Scorecard({ s, className = '' }: { s: ScoreSpec; className?: string }) {
  const tone = s.tone === 'good' ? 'text-good' : s.tone === 'bad' ? 'text-bad' : 'text-ink';
  return (
    <div className={`px-5 py-3 min-w-0 ${s.key ? 'bg-keybg' : 'bg-card'} ${className}`} data-score={s.label}>
      <div className="text-[13px] text-muted truncate max-[900px]:whitespace-normal max-[900px]:overflow-visible max-[900px]:leading-[17px]">{s.label}</div>
      <div className={`font-display text-[25px] leading-[30px] font-semibold tnum mt-0.5 ${tone}`}>{s.value}</div>
      <div className="text-[12px] text-muted min-h-[18px] truncate max-[900px]:whitespace-normal max-[900px]:overflow-visible">
        {s.note && s.tone === 'bad' ? <span className="inline-flex items-center gap-1 text-bad"><AlertTriangle size={12} />{s.note}</span>
          : s.note && s.tone === 'good' ? <span className="inline-flex items-center gap-1 text-good"><Check size={12} />{s.note}</span>
          : s.note}
      </div>
    </div>
  );
}

/** The scorecards in one soft panel, four across (two on phones), most important top-left. Max 8. */
export function ScoreGrid({ scores }: { scores: ScoreSpec[] }) {
  return (
    <section className="rounded-[14px] border border-line shadow-[var(--shadow-sm)] overflow-hidden bg-line2">
      <div className="grid grid-cols-4 max-[900px]:grid-cols-2 gap-px">
        {scores.slice(0, 8).map((s) => <Scorecard key={s.label} s={s} />)}
      </div>
    </section>
  );
}

/* ---------- horizontal stage bars --------------------------------------------- */

/** One bar: a stage, split into segments (one per client, in that client's colour). */
export interface Bar {
  /** The stage as stored (passed back on click). */
  key: string;
  /** The text at the left (usually the stage without its number). */
  label: string;
  segments: Array<{ key: string; n: number; colour: string; label?: string }>;
}

export interface BarChartProps {
  title: string;
  /** Every graph has a description (doctrine). */
  desc: string;
  bars: Bar[];
  /** Click a bar to see the records behind it. */
  onBarClick?: (barKey: string) => void;
  /** The "Open" link at the top right (e.g. go to the board). */
  onOpen?: () => void;
  /** Width of the label column. */
  labelWidth?: number;
}

/** Horizontal per-stage bars (A's look): long stage names read in full, every bar starts on the same
 *  line, one colour per client, the count at the end of the bar, hover a part for its split, click to drill. */
export function BarChart({ title, desc, bars, onBarClick, onOpen, labelWidth = 132 }: BarChartProps) {
  const totals = bars.map((b) => b.segments.reduce((n, s) => n + s.n, 0));
  const max = Math.max(1, ...totals);
  const sum = totals.reduce((a, b) => a + b, 0);
  return (
    <div className="min-w-0" data-chart={title}>
      <div className="flex items-start gap-3">
        <div className="min-w-0">
          <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
          <p className="text-[12.5px] text-muted italic">{desc}</p>
        </div>
        {onOpen && (
          <button type="button" onClick={onOpen} className="ml-auto shrink-0 text-[12px] text-ink2 inline-flex items-center gap-0.5 hover:text-ink">Open<ArrowUpRight size={12} /></button>
        )}
      </div>
      {sum ? (
        <div className="mt-3 flex flex-col gap-[3px]">
          {bars.map((b, i) => {
            const n = totals[i];
            return (
              <button key={b.key} type="button" disabled={!n || !onBarClick}
                aria-label={b.label + ': ' + n + (n && onBarClick ? ' — show these records' : '')}
                onClick={() => onBarClick && onBarClick(b.key)}
                className="flex items-center gap-2 text-left rounded-[4px] py-[2px] enabled:hover:bg-ground disabled:cursor-default">
                <span className="text-[12px] text-ink2 truncate shrink-0" style={{ width: labelWidth }}>{b.label}</span>
                <span className="flex-1 min-w-0 flex items-center gap-2">
                  <span className="flex overflow-hidden h-[10px] rounded-[3px] gap-[2px]" style={{ width: `${(n / max) * 86}%` }}>
                    {b.segments.filter((s) => s.n > 0).map((s) => <span key={s.key} className="h-full" title={(s.label || s.key) + ': ' + s.n} style={{ flex: s.n, background: s.colour }} />)}
                  </span>
                  <span className="text-[12px] font-semibold text-ink tnum">{n}</span>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="mt-3 text-[12.5px] text-faint py-4">Nothing matches the filters.</div>
      )}
    </div>
  );
}

/** The client key under a set of charts: one colour per client, the same on every chart. */
export function ClientKey({ items }: { items: Array<{ key: string; label: string; colour: string }> }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {items.map((it) => (
        <span key={it.key} className="inline-flex items-center gap-1.5 text-[11px] text-muted"><Dot colour={it.colour} size={8} />{it.label}</span>
      ))}
    </div>
  );
}
