import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Columns3, Plus, RotateCcw, Table2, X } from 'lucide-react';
import { email as authEmail } from '../lib/auth';
import { dateLong, readable } from '../lib/format';
import type { Row } from '../lib/store';
import { LinkRow } from './Field';

/** What a cell shows: text (t) or any element (node, e.g. a button column), optionally toned. */
export interface Cell { t?: React.ReactNode; node?: React.ReactNode; tone?: 'good' | 'warn' | 'bad' | 'mute' | null }

/** One column the table knows how to draw. */
export interface Column {
  label: string; w?: number; cell: (row: Row) => Cell;
  /** 'right' for number columns (header and cells). */
  align?: 'right';
}

export interface DataTableProps {
  /** Saved arrangement key: one per table per page (e.g. 'S5'). Saved per signed-in email, per browser. */
  view: string;
  rows: Row[];
  /** The named columns; any other raw field on the rows can also be added from "Add column". */
  cols: Record<string, Column>;
  /** The columns shown until the person arranges their own. The first is the identifying one. */
  defaults: string[];
  /** Columns added to `defaults` later: shown once to people who arranged theirs before; removing them sticks. */
  newCols?: string[];
  /** Raw fields never offered (ids, secrets). Fields matching hash|token|resume_key are never offered anyway. */
  hidden?: string[];
  /** Row click (doctrine: a table row opens the record). */
  onRowClick?: (row: Row) => void;
  /** Shown when there are no rows. */
  empty?: string;
  /** A red or amber edge on a row that needs looking at (a late row on My Work). */
  rowTone?: (row: Row) => 'bad' | 'warn' | null;
  /** Table title in the toolbar. */
  title?: React.ReactNode;
  /** Extra things on the toolbar's right (a page-level button). */
  right?: React.ReactNode;
  /** Draw the rows in groups, in this order: a header (name, count) that folds, then its rows,
   *  numbered from 1 in each group. Every row in `groups` must also be in `rows`. */
  groups?: TableGroup[];
}

/** One group of rows: its key, the header's name (and a colour square), and its rows. */
export interface TableGroup { key: string; label: string; colour?: string; rows: Row[] }

/* ---------- saved arrangements (per signed-in email, per browser) ---- */

interface Saved { order?: string[]; widths?: Record<string, number>; seen?: string[] }
function viewKey(view: string) { return 'os-view:' + (authEmail() || 'anyone') + ':' + view; }
function loadView(view: string): Saved | null {
  try { return JSON.parse(localStorage.getItem(viewKey(view)) || 'null'); } catch { return null; }
}
function saveView(view: string, v: Saved | null) {
  try { if (v) localStorage.setItem(viewKey(view), JSON.stringify(v)); else localStorage.removeItem(viewKey(view)); } catch { /* private window */ }
}

/* A raw field as a cell. */
function plain(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.length ? v.map(plain).join(', ') : '—';
  if (typeof v === 'object') return 'value' in (v as object) ? plain((v as { value: unknown }).value) : Object.keys(v as object).length + ' fields';
  if (/^\d{4}-\d\d-\d\dT/.test(String(v))) return dateLong(String(v));
  return String(v);
}
/** The cell for any raw field (exported for screens that build their own columns). Links get the address + Open button. */
export function rawCell(_k: string, v: unknown): Cell {
  if (typeof v === 'string' && /^https?:\/\/\S+$/.test(v.trim())) return { node: <LinkRow url={v.trim()} /> };
  return { t: plain(v) };
}

const TONE: Record<string, string> = { good: 'text-good', warn: 'text-warn', bad: 'text-bad', mute: 'text-muted' };

/** The table (E's look): dense grid, resizable columns (drag the edge), re-orderable (drag a header),
 *  "Add column" for any other field, × to hide. The arrangement is saved per login, per browser.
 *  Scrolls sideways inside its own frame. */
export function DataTable({ view, rows, cols, defaults, newCols = [], hidden = [], onRowClick, rowTone, empty = 'Nothing here yet', title, right, groups }: DataTableProps) {
  const [, force] = useState(0);
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const refresh = () => force((n) => n + 1);
  const [menu, setMenu] = useState(false);
  const [overCol, setOverCol] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const dragFrom = useRef<string | null>(null);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menu]);

  // Every column on offer: the named ones, then every other raw field the rows carry.
  const offered: Record<string, Column> = { ...cols };
  rows.forEach((r) => Object.keys(r).forEach((k) => {
    if (offered[k] || hidden.indexOf(k) > -1 || /hash|token|resume_key/.test(k)) return;
    offered[k] = { label: readable(k), w: /url|link|doc|drive/.test(k) ? 340 : 170, cell: (row) => rawCell(k, row[k]) };
  }));

  const saved = loadView(view) || {};
  const seen = saved.seen || defaults.filter((k) => newCols.indexOf(k) < 0);
  let order = (saved.order || defaults).filter((k) => offered[k]);
  if (saved.order) defaults.forEach((k) => {
    if (seen.indexOf(k) < 0 && order.indexOf(k) < 0 && offered[k]) order.splice(Math.min(defaults.indexOf(k), order.length), 0, k);
  });
  if (!order.length) order = defaults.filter((k) => offered[k]);
  const widths: Record<string, number> = { ...(saved.widths || {}) };
  const width = (k: string) => Math.max(80, widths[k] || offered[k].w || 170);
  const persist = (o: string[], w: Record<string, number>) => {
    const all = seen.concat(defaults.filter((k) => seen.indexOf(k) < 0));
    saveView(view, { order: o, widths: w, seen: all });
  };

  const addable = Object.keys(offered).filter((k) => order.indexOf(k) < 0)
    .sort((a, b) => offered[a].label.localeCompare(offered[b].label));

  function startResize(e: React.MouseEvent, k: string) {
    e.preventDefault(); e.stopPropagation();
    const startX = e.clientX, startW = width(k);
    const cells = wrap.current ? wrap.current.querySelectorAll<HTMLElement>('[data-col="' + CSS.escape(k) + '"]') : [];
    const move = (ev: MouseEvent) => {
      const w = Math.max(80, startW + ev.clientX - startX);
      widths[k] = w;
      cells.forEach((c) => { c.style.width = w + 'px'; });
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.body.classList.remove('os-resizing');
      persist(order, widths); refresh();
    };
    document.body.classList.add('os-resizing');
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  }

  const total = 44 + order.reduce((n, k) => n + width(k), 0);
  const cellBase = 'shrink-0 px-3 flex items-center border-r border-line2 min-w-0';
  const row = (r: Row, i: number) => {
    const tone = rowTone ? rowTone(r) : null;
    return (
      <div key={r.id || i} role="row" tabIndex={onRowClick ? 0 : undefined} data-row-tone={tone || undefined}
        style={{ boxShadow: tone ? 'inset 3px 0 0 var(--' + tone + ')' : undefined }}
        className={`flex min-h-[38px] border-b border-line2 ${onRowClick ? 'cursor-pointer hover:bg-ground focus:bg-ground focus:outline-none' : ''}`}
        onClick={onRowClick ? () => onRowClick(r) : undefined}
        onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(r); } : undefined}>
        <div className={`${cellBase} w-[44px] justify-center text-faint text-[12px] tnum`}>{i + 1}</div>
        {order.map((k, j) => {
          const c = offered[k].cell(r) || {};
          return (
            <div key={k} data-col={k} className={`${cellBase} py-1.5 ${c.tone ? TONE[c.tone] : j === 0 ? 'font-medium text-ink' : 'text-ink2'} ${c.tone && j === 0 ? 'font-medium' : ''} ${offered[k].align === 'right' ? 'justify-end text-right tnum' : ''}`} style={{ width: width(k) }}>
              {c.node !== undefined ? c.node : <span className="truncate">{c.t === undefined || c.t === null || c.t === '' ? '—' : c.t}</span>}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="rounded-[14px] bg-card border border-line shadow-[var(--shadow-sm)] overflow-hidden" data-table={view}>
      {/* With controls on the right, the row wraps on a narrow screen instead of cutting them off. */}
      <div className={`${right ? 'min-h-[44px] py-1.5 flex-wrap' : 'h-[44px]'} px-4 flex items-center gap-2 text-[12.5px] border-b border-line whitespace-nowrap`}>
        {title && <span className="inline-flex items-center gap-1.5 font-semibold text-ink text-[13.5px]"><Table2 size={14} />{title}</span>}
        <span className="text-faint">{rows.length} {rows.length === 1 ? 'row' : 'rows'} · {order.length} columns</span>
        <div className="relative ml-2">
          <button type="button" aria-expanded={menu} disabled={!addable.length}
            className="inline-flex items-center gap-1 h-[28px] px-2 rounded-[8px] text-ink2 border border-line disabled:opacity-50"
            onClick={(e) => { e.stopPropagation(); setMenu((m) => !m); }}>
            <Columns3 size={12} />Add column<Plus size={12} />
          </button>
          {menu && (
            <div role="menu" className="absolute z-30 left-0 top-[32px] w-[240px] max-h-[320px] overflow-y-auto rounded-[10px] bg-card border border-line shadow-[var(--shadow-lg)] py-1"
              onClick={(e) => e.stopPropagation()}>
              {addable.map((k) => (
                <button key={k} type="button" role="menuitem" className="block w-full text-left px-3 py-1.5 text-[13px] text-ink2 hover:bg-ground"
                  onClick={() => { persist(order.concat([k]), widths); setMenu(false); refresh(); }}>{offered[k].label}</button>
              ))}
            </div>
          )}
        </div>
        {(saved.order || saved.widths) && (
          <button type="button" className="inline-flex items-center gap-1 h-[28px] px-2 rounded-[8px] text-muted hover:text-ink"
            onClick={() => { saveView(view, null); refresh(); }}><RotateCcw size={12} />Reset columns</button>
        )}
        {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
      </div>

      <div ref={wrap} className="overflow-x-auto" data-scroll>
        <div style={{ width: total, minWidth: '100%' }} className="text-[13px]">
          <div className="flex h-[36px] bg-ground border-b border-line text-[12px] text-muted font-medium" role="row">
            <div className={`${cellBase} w-[44px] justify-center text-faint`}>#</div>
            {order.map((k) => (
              <div key={k} data-col={k} role="columnheader" draggable
                className={`${cellBase} relative group gap-1 cursor-grab ${overCol === k ? 'bg-taccent' : ''}`} style={{ width: width(k) }}
                onDragStart={(e) => { dragFrom.current = k; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', k); }}
                onDragOver={(e) => { e.preventDefault(); if (overCol !== k) setOverCol(k); }}
                onDragLeave={() => setOverCol((c) => (c === k ? null : c))}
                onDrop={(e) => {
                  e.preventDefault(); setOverCol(null);
                  const from = dragFrom.current || e.dataTransfer.getData('text/plain');
                  dragFrom.current = null;
                  if (!from || from === k || order.indexOf(from) < 0) return;
                  const next = order.slice(); next.splice(next.indexOf(from), 1); next.splice(next.indexOf(k), 0, from);
                  persist(next, widths); refresh();
                }}>
                <span className={`truncate flex-1 ${offered[k].align === 'right' ? 'text-right' : ''}`}>{offered[k].label}</span>
                {order.length > 1 && (
                  // Laid over the right edge (it takes no room), so it never cuts the label short.
                  <button type="button" aria-label={'Hide ' + offered[k].label} data-hide-col
                    className="absolute right-[6px] top-1/2 -translate-y-1/2 z-[5] inline-flex opacity-0 group-hover:opacity-100 focus:opacity-100 items-center justify-center w-[18px] h-[18px] rounded-[4px] bg-ground text-faint hover:text-ink"
                    onClick={(e) => { e.stopPropagation(); persist(order.filter((x) => x !== k), widths); refresh(); }}><X size={12} /></button>
                )}
                <span aria-hidden draggable={false} className="absolute right-[-3px] top-0 bottom-0 w-[7px] cursor-col-resize z-10 hover:bg-[var(--border-focus)]"
                  onMouseDown={(e) => startResize(e, k)} onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }} />
              </div>
            ))}
          </div>
          {groups ? groups.map((g) => (
            <div key={g.key} data-group={g.key} data-group-count={g.rows.length} data-folded={folded[g.key] ? '' : undefined}>
              <button type="button" aria-expanded={!folded[g.key]} onClick={() => setFolded((m) => ({ ...m, [g.key]: !m[g.key] }))}
                className="w-full flex items-center h-[36px] bg-ground/60 border-b border-line2 text-left hover:bg-ground" data-group-head>
                <span className="sticky left-0 inline-flex items-center gap-2 px-3 text-[13px] font-semibold text-ink">
                  {folded[g.key] ? <ChevronRight size={14} className="text-muted" /> : <ChevronDown size={14} className="text-muted" />}
                  {g.colour && <span className="w-[10px] h-[10px] rounded-[3px] shrink-0" style={{ background: g.colour }} />}
                  <span data-group-label>{g.label}</span>
                  <span className="font-normal text-muted tnum">({g.rows.length})</span>
                </span>
              </button>
              {!folded[g.key] && g.rows.map((r, i) => row(r, i))}
            </div>
          )) : rows.map((r, i) => row(r, i))}
        </div>
        {/* Outside the wide inner box, so it is centred on what can be seen, not on the whole
            table width (on a phone the table is wider than the screen). */}
        {!rows.length && <div data-table-empty className="sticky left-0 px-4 py-8 text-center text-[13px] text-faint">{empty}</div>}
      </div>
    </div>
  );
}
