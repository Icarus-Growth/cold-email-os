/* One field of a record, drawn from its FieldDef: a value to read, or a box to edit that
 * saves when the person clicks away. Every record page and panel uses this, so a field
 * looks and behaves the same everywhere. */
import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';
import type { FieldDef, SectionDef } from '../../config';
import { LinkRow, RichText, RichView, Select, TextInput, Toggle, type FieldSpec, type SectionSpec } from '../../ui';
import { patch, type Data, type Row } from '../../lib/store';
import { cardPath, listOf, recordDef } from '../../lib/schema';
import { dateLong, dateTime, localStamp, readable } from '../../lib/format';
import { inApp } from '../../lib/router';
import { DocField } from '../docs/DocField';

const empty = (v: unknown) => v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length);

/** A number as people read it. */
export function showNumber(v: unknown, format: 'int' | 'number' | 'money' | 'percent' | 'url'): string {
  if (empty(v)) return '—';
  if (format === 'url') return String(v);
  const n = Number(v);
  if (isNaN(n)) return String(v);
  if (format === 'percent') return (n * 100).toFixed(1) + '%';
  if (format === 'money') return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n.toLocaleString();
}

/** "2026-10-01" -> "Oct 2026". */
function monthText(v: unknown): string {
  if (empty(v)) return '—';
  const d = new Date(String(v).slice(0, 10) + 'T12:00:00');
  return isNaN(d.getTime()) ? String(v) : d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
}

/** The card a 'card' field points at (archived ones too), or null. */
export function linkedCard(S: Data, f: FieldDef, v: unknown): Row | null {
  if (empty(v) || !f.board) return null;
  return S.allRows(f.board).find((r) => r.id === v) || null;
}

/** A linked card's name ("Untitled campaign" when it has none, "A card that is gone" when deleted). */
export function linkedName(S: Data, f: FieldDef, v: unknown): string {
  const def = recordDef(f.board);
  const row = linkedCard(S, f, v);
  if (!row) return 'A card that is gone';
  return String(row[def ? def.nameKey : 'id'] || 'Untitled ' + (def ? def.item : 'card')) + (row.archived_at ? ' (archived)' : '');
}

/** The pick list for a 'card' field: the cards of the row's own client (all clients when the
 *  row has none), not archived, A to Z, plus the one set now. */
export function cardOptions(S: Data, f: FieldDef, row: Row | null, current?: unknown): Array<[string, string]> {
  const def = recordDef(f.board);
  if (!def) return [];
  const client = row ? row.client_id : null;
  const list = S.rows(def.table).filter((r) => !client || r.client_id === client)
    .map((r): [string, string] => [r.id, String(r[def.nameKey] || 'Untitled ' + def.item)])
    .sort((a, b) => a[1].localeCompare(b[1]));
  if (current && !list.some((o) => o[0] === current)) list.push([String(current), linkedName(S, f, current)]);
  return list;
}

/** The value of a field as text (read only). */
export function showValue(S: Data, f: FieldDef, v: unknown): string {
  if (empty(v)) return '—';
  switch (f.type) {
    case 'person': return S.teamName(String(v)) || 'Someone not on the team';
    case 'client': return S.clientName(String(v));
    case 'card': return linkedName(S, f, v);
    case 'date': return dateLong(String(v) + (String(v).length === 10 ? 'T12:00:00' : ''));
    case 'datetime': return dateTime(String(v));
    case 'month': return monthText(v);
    case 'bool': return v ? 'Yes' : 'No';
    case 'tags': return Array.isArray(v) ? v.join(', ') : String(v);
    case 'int': case 'number': case 'money': case 'percent': return showNumber(v, f.type);
    default: return String(v);
  }
}

/** The person options: the active team, plus whoever is set now (even if they left). */
function people(S: Data, current: unknown): Array<[string, string]> {
  const list = S.activeTeam.map((t): [string, string] => [t.id, t.full_name]);
  if (current && !list.some((o) => o[0] === current) && S.teamById[String(current)]) list.push([String(current), S.teamById[String(current)].full_name + ' (inactive)']);
  return list;
}
/** The client options: every client that is not archived, A to Z, plus the current one if it is. */
export function clientOptions(S: Data, current?: unknown): Array<[string, string]> {
  const list = S.rows('clients').map((c): [string, string] => [c.id, c.client_name || 'Unnamed client'])
    .sort((a, b) => a[1].localeCompare(b[1]));
  const cur = current ? S.clientById[String(current)] : null;
  if (cur && cur.archived_at) list.push([cur.id, (cur.client_name || 'Unnamed client') + ' (archived)']);
  return list;
}

/** The editor for one field; `save` gets the new value (null when emptied). */
export function editor(S: Data, f: FieldDef, v: unknown, save: (value: unknown) => void, name: string, row: Row | null = null): ReactNode {
  const text = empty(v) ? '' : String(v);
  const label = f.label;
  switch (f.type) {
    case 'longtext':
      return <RichText value={text} field={name} aria-label={label} onSave={(html) => save(html)} />;
    case 'bool':
      return <Toggle checked={!!v} onChange={(on) => save(on)} label={v ? 'Yes' : 'No'} />;
    case 'person':
      return <Select aria-label={label} value={text} placeholder="Nobody" options={people(S, v)} onChange={(x) => save(x || null)} />;
    case 'client':
      return <Select aria-label={label} value={text} placeholder={f.required ? 'Pick a client' : 'No client'} options={clientOptions(S, v)}
        onChange={(x) => { if (x || !f.required) save(x || null); }} />;
    case 'card': {
      const def = recordDef(f.board);
      return <Select aria-label={label} value={text} placeholder={'No ' + (def ? def.item : 'card')} options={cardOptions(S, f, row, v)} onChange={(x) => save(x || null)} />;
    }
    case 'choice': {
      const opts = (f.options || listOf(f.list)).map((o): [string, string] => [o, o]);
      if (text && !opts.some((o) => o[0] === text)) opts.push([text, text]);
      return <Select aria-label={label} value={text} options={opts} onChange={(x) => save(x)} />;
    }
    case 'date':
      return <TextInput type="date" aria-label={label} field={name} value={text.slice(0, 10)} onSave={(x) => save(x || null)} />;
    case 'datetime':
      return <TextInput type="datetime-local" aria-label={label} field={name} value={localStamp(text)}
        onSave={(x) => save(x ? new Date(x).toISOString() : null)} />;
    case 'month':
      return <input type="month" aria-label={label} data-field={name} defaultValue={text.slice(0, 7)}
        className="w-full h-[34px] rounded-[10px] border border-line bg-card px-3 text-[13px] text-ink focus:outline-none focus:border-[var(--border-focus)]"
        onBlur={(e) => { const x = e.target.value; if (x && x !== text.slice(0, 7)) save(x + '-01'); }} />;
    case 'int': case 'number': case 'money': case 'percent':
      return <TextInput type="number" aria-label={label} field={name} value={text}
        onSave={(x) => save(x === '' ? null : f.type === 'int' ? Math.round(Number(x)) : Number(x))} />;
    case 'tags':
      return <TextInput aria-label={label} field={name} value={Array.isArray(v) ? v.join(', ') : text}
        onSave={(x) => save(x.split(',').map((s) => s.trim()).filter(Boolean))} />;
    case 'url':
      return (
        <div className="flex items-center gap-2 min-w-0">
          <TextInput type="url" aria-label={label} field={name} value={text} placeholder="https://" onSave={(x) => save(x.trim() || null)} />
          {/^https?:\/\//.test(text) && (
            <a href={text} target="_blank" rel="noopener noreferrer" aria-label={'Open ' + label}
              className="shrink-0 inline-flex items-center justify-center w-[34px] h-[34px] rounded-[10px] border border-line bg-card text-ink2 hover:bg-ground">
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      );
    default:
      return <TextInput type={f.type === 'email' ? 'email' : 'text'} aria-label={label} field={name} value={text}
        onSave={(x) => save(f.type === 'email' ? x.trim().toLowerCase() || null : x.trim() || (f.required ? text : null))} />;
  }
}

/** A read-only value, with links and people made useful. */
function reader(S: Data, f: FieldDef, v: unknown): FieldSpec {
  if (f.type === 'longtext') return { k: f.label, desc: f.desc, node: <RichView value={empty(v) ? '' : String(v)} /> };
  if (f.type === 'url' && !empty(v)) return { k: f.label, desc: f.desc, node: <LinkRow url={String(v)} label="Open" /> };
  if (f.type === 'client' && !empty(v)) {
    const to = '/clients/' + encodeURIComponent(String(v));
    return { k: f.label, desc: f.desc, node: <a href={to} onClick={(e) => inApp(e, to)} className="text-ink2 underline underline-offset-2">{showValue(S, f, v)}</a> };
  }
  if (f.type === 'card' && !empty(v) && f.board && linkedCard(S, f, v)) {
    const to = cardPath(f.board, String(v));
    return { k: f.label, desc: f.desc, node: <a href={to} onClick={(e) => inApp(e, to)} className="text-ink2 underline underline-offset-2">{showValue(S, f, v)}</a> };
  }
  return { k: f.label, desc: f.desc, v: showValue(S, f, v), tone: empty(v) ? 'mute' : null };
}

/** One field of a row as a FieldSpec: an editor when the person may edit it, else the value. */
export function fieldSpec(S: Data, table: string, row: Row, f: FieldDef, canEdit = true): FieldSpec {
  if (f.type === 'document') return { k: f.label, desc: f.desc, node: <DocField table={table} row={row} f={f} canEdit={canEdit && !f.readOnly} /> };
  const v = row[f.key];
  if (!canEdit || f.readOnly) return reader(S, f, v);
  const save = (value: unknown) => {
    if (value === v || (empty(value) && empty(v))) return;
    patch(table, row.id, { [f.key]: value }).catch(() => { /* the store put it back and said so */ });
  };
  const node = editor(S, f, v, save, table + ':' + row.id + ':' + f.key, row);
  if (f.type === 'card' && !empty(v) && f.board && linkedCard(S, f, v)) {
    const to = cardPath(f.board, String(v));
    return { k: f.label, desc: f.desc, node: (
      <div className="flex items-center gap-2 min-w-0">
        <div className="flex-1 min-w-0">{node}</div>
        <a href={to} onClick={(e) => inApp(e, to)} aria-label={'Open ' + f.label}
          className="shrink-0 inline-flex items-center justify-center w-[34px] h-[34px] rounded-[10px] border border-line bg-card text-ink2 hover:bg-ground">
          <ExternalLink size={14} />
        </a>
      </div>
    ) };
  }
  return { k: f.label, desc: f.desc, node };
}

/** Who may edit what: true or false for every field, or a test per column. */
export type CanEdit = boolean | ((key: string) => boolean);

function may(canEdit: CanEdit | undefined, key: string): boolean {
  return typeof canEdit === 'function' ? canEdit(key) : canEdit !== false;
}

/** A SectionDef as a SectionSpec for a row. Fields the row does not have are left out. */
export function sectionSpec(S: Data, table: string, row: Row, s: SectionDef, opts: { canEdit?: CanEdit; fold?: boolean; foldKey?: string } = {}): SectionSpec {
  return {
    title: s.title, desc: s.desc, fold: opts.fold, foldKey: opts.foldKey, closed: s.closed,
    fields: s.fields.filter((f) => f.key in row || f.type === 'document').map((f) => fieldSpec(S, table, row, f, may(opts.canEdit, f.key))),
  };
}

/** The columns a list of fields shows: each field's own, and a document's link column. */
export function keysOf(fields: FieldDef[]): string[] {
  return fields.flatMap((f) => (f.link ? [f.key, f.link] : [f.key]));
}

/** Columns the row carries that no section shows (an Interview answer added them, or a
 *  column you added yourself). Ids, times and example marks go to "For developers". */
export function extraFields(row: Row, shown: string[]): FieldDef[] {
  return Object.keys(row)
    .filter((k) => shown.indexOf(k) < 0 && !isDevColumn(k))
    .map((k): FieldDef => {
      const v = row[k];
      const type = typeof v === 'boolean' ? 'bool' : typeof v === 'number' ? 'number' : Array.isArray(v) ? 'tags'
        : /_url$/.test(k) ? 'url' : /_(date|on)$/.test(k) ? 'date' : /_at$/.test(k) ? 'datetime' : 'text';
      return { key: k, label: readable(k), type, readOnly: v !== null && typeof v === 'object' && !Array.isArray(v) };
    });
}

/** Ids, times and marks: shown only in "For developers". */
export function isDevColumn(k: string): boolean {
  if (k === 'id' || k === 'is_example' || k === 'form_code') return true;
  if (/^(created_at|updated_at|archived_at|mcp_last_seen_at)$/.test(k) || /_changed_(at|by_id)$/.test(k)) return true;
  if (k === 'slack_channel_id') return false; // edited on the client page
  // A link to another row is an id, except the people in a role (they are picked by name).
  return /_id$/.test(k) && !/(manager|buyer|editor|writer|designer|builder|assignee|reviewer|copywriter)_id$/.test(k);
}

/** The "For developers" section: every id and time on the row, closed until opened. */
export function devSection(S: Data, table: string, row: Row, known: FieldDef[] = [], canEdit?: CanEdit): SectionSpec {
  const keys = known.map((f) => f.key);
  const more = Object.keys(row).filter((k) => keys.indexOf(k) < 0 && isDevColumn(k))
    .map((k): FieldDef => ({ key: k, label: readable(k) + (/_id$/.test(k) ? ' ID' : ''), type: /_at$/.test(k) ? 'datetime' : typeof row[k] === 'boolean' ? 'bool' : 'text', readOnly: true }));
  return {
    title: 'For developers', desc: 'The ids and times the database keeps. You rarely need these.',
    fold: true, closed: true, foldKey: 'dev:' + table,
    fields: known.concat(more).filter((f) => f.key in row).map((f) => fieldSpec(S, table, row, f, may(canEdit, f.key))),
  };
}
