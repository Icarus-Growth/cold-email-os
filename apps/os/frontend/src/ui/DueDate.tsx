/* The due-date filter of a list: a pill with ranges counted in days ("Late", "Today",
 * "Next 7 days", "Between two dates", "No due date"). Days are the viewer's own calendar
 * days. The value is a short string kept in the filter store ("next7", "between:2026-10-01:2026-10-10"),
 * so it survives a page change. (DatePill in Filters.tsx is a single date box; this one is RangePill.) */
import { ChevronDown } from 'lucide-react';
import { dayKey } from '../lib/format';

export { dayKey };
/** The local midnight of a 'YYYY-MM-DD' day. */
export function dayDate(key: string): Date {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, m - 1, d);
}
export function addDays(key: string, n: number): string {
  const d = dayDate(key);
  d.setDate(d.getDate() + n);
  return dayKey(d);
}
/** The day a stored value falls on: a date column ('2026-10-11') as it is, a timestamp in local time. */
export function dayOf(v: unknown): string | null {
  if (!v) return null;
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const t = Date.parse(s);
  return isNaN(t) ? null : dayKey(t);
}

export interface DayRange { from: string; to: string }
export const DATE_LABEL: Record<string, string> = {
  any: 'Any date',
  past7: 'Past 7 days', past30: 'Past 30 days', next7: 'Next 7 days', next30: 'Next 30 days',
  thisMonth: 'This month', nextMonth: 'Next month',
  between: 'Between two dates',
  /* Due dates: late is past due, none is no due date at all. */
  late: 'Late', today: 'Today', none: 'No due date',
};

/** The days a filter value covers, both ends included; null = any date. "Past N days" and
 *  "Next N days" both include today. */
export function resolveRange(value: string, today: string = dayKey(new Date())): DayRange | null {
  if (value.indexOf('between:') === 0) {
    const [, a, b] = value.split(':');
    if (!a || !b) return null;
    return a <= b ? { from: a, to: b } : { from: b, to: a };
  }
  if (value === 'today') return { from: today, to: today };
  const m = /^(past|next)(\d+)$/.exec(value);
  if (m) {
    const n = Number(m[2]);
    return m[1] === 'past' ? { from: addDays(today, 1 - n), to: today } : { from: today, to: addDays(today, n - 1) };
  }
  if (/^(this|last|next)Month$/.test(value)) {
    const d = dayDate(today);
    const shift = value === 'lastMonth' ? -1 : value === 'nextMonth' ? 1 : 0;
    const first = new Date(d.getFullYear(), d.getMonth() + shift, 1);
    const last = new Date(d.getFullYear(), d.getMonth() + shift + 1, 0);
    return { from: dayKey(first), to: dayKey(last) };
  }
  return null;
}

/** The range pill, plus two date boxes when "Between two dates" is chosen. */
export function RangePill({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  const between = value.indexOf('between') === 0;
  const kind = between ? 'between' : value;
  /* "Between" starts on the past 7 days, or on the next 7 when the pill only looks ahead (due dates). */
  const ahead = !options.some((o) => /^past/.test(o));
  const today = dayKey(new Date());
  const r = resolveRange(value) || (ahead ? { from: today, to: addDays(today, 6) } : { from: addDays(today, -6), to: today });
  const box = 'h-[32px] px-2.5 rounded-full border border-line bg-card text-[13px] text-ink';
  return (
    <span className="inline-flex items-center gap-2 flex-wrap" data-date-filter={label}>
      <label className={`relative h-[32px] pl-3 pr-7 rounded-full border text-[13px] inline-flex items-center gap-1.5 whitespace-nowrap cursor-pointer hover:border-[var(--border-primary_hover)] ${kind !== options[0] ? 'bg-taccent border-[var(--border-brand)]' : 'bg-card border-line'}`}>
        <span className="text-muted">{label}</span>
        <span className="text-ink font-medium">{DATE_LABEL[kind] || kind}</span>
        <ChevronDown size={13} className="text-faint absolute right-2.5" />
        <select aria-label={label} value={kind} className="absolute inset-0 opacity-0 cursor-pointer w-full"
          onChange={(e) => onChange(e.target.value === 'between' ? 'between:' + r.from + ':' + r.to : e.target.value)}>
          {options.map((o) => <option key={o} value={o}>{DATE_LABEL[o] || o}</option>)}
        </select>
      </label>
      {between && (
        <>
          <input type="date" aria-label={label + ' from'} className={box} value={r.from} data-date-from
            onChange={(e) => e.target.value && onChange('between:' + e.target.value + ':' + r.to)} />
          <span className="text-[12.5px] text-muted">to</span>
          <input type="date" aria-label={label + ' to'} className={box} value={r.to} data-date-to
            onChange={(e) => e.target.value && onChange('between:' + r.from + ':' + e.target.value)} />
        </>
      )}
    </span>
  );
}
