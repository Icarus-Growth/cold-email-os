/* Sort for a list view: one field, ascending or descending, or the list's own default order.
 * Generic: the screen says which fields it offers and how to read each one off a row.
 * Empty values (none, blank, not a number) go last in both directions, and rows with the
 * same value keep the order they came in, so a sort inside groups never moves the groups. */
import { ArrowDown, ArrowUp } from 'lucide-react';
import { ChoicePill } from './Filters';

export type SortDir = 'asc' | 'desc';
export type SortValue = string | number | null | undefined;
/** The stored choice: 'default', or '<field>:asc' / '<field>:desc'. */
export interface SortChoice { field: string; dir: SortDir }

export function readSort(stored: string | null | undefined): SortChoice {
  const [field, dir] = String(stored || 'default').split(':');
  return { field: field || 'default', dir: dir === 'desc' ? 'desc' : 'asc' };
}
export const writeSort = (c: SortChoice) => (c.field === 'default' ? 'default' : c.field + ':' + c.dir);

const isEmpty = (v: SortValue) => v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v));

/** A sorted copy. Numbers compare as numbers, text without case and with numbers in order. */
export function sortList<T>(list: T[], value: (x: T) => SortValue, dir: SortDir): T[] {
  return list.map((x, i) => ({ x, i, v: value(x) })).sort((a, b) => {
    const ea = isEmpty(a.v), eb = isEmpty(b.v);
    if (ea || eb) return ea === eb ? a.i - b.i : ea ? 1 : -1;
    const c = typeof a.v === 'number' && typeof b.v === 'number' ? a.v - b.v
      : String(a.v).localeCompare(String(b.v), undefined, { sensitivity: 'base', numeric: true });
    return (dir === 'desc' ? -c : c) || a.i - b.i;
  }).map((e) => e.x);
}

/** "Sort  Default ⌄", and once a field is picked, a button that turns the direction round. */
export function SortPill({ fields, choice, onChange, label = 'Sort' }: {
  fields: Array<[string, string]>; choice: SortChoice; onChange: (c: SortChoice) => void; label?: string;
}) {
  const all: Array<[string, string]> = [['default', 'Default'] as [string, string]].concat(fields);
  const shown = (all.find((f) => f[0] === choice.field) || all[0])[1];
  const asc = choice.dir === 'asc';
  return (
    <span className="inline-flex items-center gap-1.5" data-sort={choice.field} data-sort-dir={choice.field === 'default' ? undefined : choice.dir}>
      <ChoicePill label={label} value={shown} options={all.map((f) => f[1])}
        onChange={(v) => onChange({ field: (all.find((f) => f[1] === v) || all[0])[0], dir: choice.dir })} />
      {choice.field !== 'default' && (
        <button type="button" onClick={() => onChange({ field: choice.field, dir: asc ? 'desc' : 'asc' })} data-sort-flip
          aria-label={asc ? 'Ascending. Change to descending' : 'Descending. Change to ascending'}
          className="h-[32px] px-3 rounded-full border border-line bg-card text-[13px] text-ink2 inline-flex items-center gap-1.5 hover:text-ink hover:border-[var(--border-primary_hover)]">
          {asc ? <ArrowUp size={13} /> : <ArrowDown size={13} />}{asc ? 'Ascending' : 'Descending'}
        </button>
      )}
    </span>
  );
}
