import React, { useRef, useState } from 'react';
import { type LucideIcon } from 'lucide-react';
import { Avatar, Dot, StageGlyph } from './Tag';
import { setDragging } from '../lib/store';
import { shortStage } from '../lib/format';
import { useRoute } from '../lib/router';
import { tinyStore } from '../lib/tinyStore';

/* Folded columns, keyed "<screen>:<stage>" (the live app's state.columns). Kept for the app
 * session, per screen: leave a board and come back and the same columns are folded. */
const folded = tinyStore<Record<string, boolean>>({});
/** Fold or unfold one column (exported for tests). */
export function toggleColumn(key: string): void { folded.set((f) => ({ ...f, [key]: !f[key] })); }

/** One line on a card. Three per card, never four. */
export interface CardField {
  text: React.ReactNode;
  icon?: LucideIcon;
  /** Shows an avatar with these initials instead of an icon (the assignee line). */
  who?: string | null;
  tone?: 'warn' | 'bad' | 'good' | null;
}

export interface BoardCard {
  id: string;
  /** The stage (column) it sits in, exactly as stored. */
  stage: string;
  title: React.ReactNode;
  /** The client's chart colour, shown as a square before the title. */
  colour?: string;
  /** Up to three; anything after the third is dropped. */
  fields: CardField[];
  /** Sort key inside a column: newest first (usually updated_at). */
  sort?: string | number | null;
  /** A red edge (late, blocked). */
  alert?: boolean;
}

export interface KanbanBoardProps {
  /** Every stage gets a column, empty or not, in this order. */
  stages: readonly string[];
  cards: BoardCard[];
  onOpen: (id: string) => void;
  /** Leave out to make the board read-only (no drag): e.g. Inbox Setup, moved by the server. */
  onMove?: (id: string, stage: string) => void;
  /** The card whose record is open (outlined). */
  selectedId?: string | null;
  /** Column title. Default: the stage name without its number ("0 - Backlog" -> "Backlog"). */
  label?: (stage: string) => string;
  /** Stages shown in red (Blocked, Rejected). */
  exception?: (stage: string) => boolean;
  /** Sort cards in a column; default newest `sort` first. */
  compare?: (a: BoardCard, b: BoardCard) => number;
  /** Text in an empty column. */
  empty?: string;
  /** Fold key prefix. Default: the screen the board is on, so each board keeps its own folds. */
  view?: string;
}

/** The board (B's look). Every stage is a column; each column scrolls on its own; the board
 *  scrolls sideways inside its frame, never the page. Drag a card to another column to move it.
 *  Nothing re-renders while a card is held, so the drag is never cancelled. */
export function KanbanBoard({ stages, cards, onOpen, onMove, selectedId, label = shortStage, exception, compare, empty = 'Nothing here', view }: KanbanBoardProps) {
  const route = useRoute();
  const fold = folded.use();
  const prefix = (view || route.screen) + ':';
  const [over, setOver] = useState<string | null>(null);
  const [landed, setLanded] = useState<string | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const held = useRef<string | null>(null);

  const byStage: Record<string, BoardCard[]> = {};
  stages.forEach((s) => { byStage[s] = []; });
  cards.forEach((c) => { (byStage[c.stage] = byStage[c.stage] || []).push(c); });
  const cmp = compare || ((a: BoardCard, b: BoardCard) => String(b.sort ?? '').localeCompare(String(a.sort ?? '')));

  function drop(stage: string, e: React.DragEvent) {
    e.preventDefault();
    setOver(null);
    const id = held.current || e.dataTransfer.getData('text/plain');
    held.current = null;
    setDragging(false);
    if (!id || !onMove) return;
    const card = cards.find((c) => c.id === id);
    if (!card || card.stage === stage) return;
    setLanded(id);
    setTimeout(() => setLanded((x) => (x === id ? null : x)), 700);
    onMove(id, stage);
  }

  return (
    <div ref={frame} data-board className="flex gap-3 h-full min-h-0 overflow-x-auto overflow-y-hidden pb-2 overscroll-x-contain"
      onDragOver={(e) => {
        // Near the left or right edge, a held card scrolls the board.
        const el = frame.current; if (!el || !held.current) return;
        const r = el.getBoundingClientRect(), zone = 60;
        if (e.clientX < r.left + zone) el.scrollLeft -= 18;
        else if (e.clientX > r.right - zone) el.scrollLeft += 18;
      }}>
      {stages.map((stage) => {
        const list = (byStage[stage] || []).slice().sort(cmp);
        const bad = exception ? exception(stage) : false;
        const key = prefix + stage;
        const dropProps = onMove ? {
          onDragOver: (e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (over !== stage) setOver(stage); },
          onDragLeave: (e: React.DragEvent) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) setOver((s) => (s === stage ? null : s)); },
          onDrop: (e: React.DragEvent) => drop(stage, e),
        } : {};
        if (fold[key]) {
          // Folded: a narrow strip with the count and the title on its side. Click to unfold.
          // A card can still be dropped on it.
          return (
            <button key={stage} type="button" data-column={stage} data-folded=""
              aria-label={label(stage) + ' — ' + list.length + ', click to open'} title={stage}
              onClick={() => toggleColumn(key)} {...dropProps}
              className={`w-[48px] shrink-0 flex flex-col items-center gap-2 py-2.5 rounded-[14px] border border-line cursor-pointer hover:border-[var(--border-focus)] ${over === stage ? 'ring-2 ring-[var(--border-focus)]' : ''}`}
              style={{ background: bad ? 'var(--tint-bad)' : 'rgba(230,226,217,.45)' }}>
              <StageGlyph stage={stage} ladder={stages} size={13} />
              <span className="text-[12px] text-muted tnum px-1.5 rounded-full bg-chrome">{list.length}</span>
              <span className={`text-[13px] font-semibold whitespace-nowrap ${bad ? 'text-bad' : 'text-ink'}`} style={{ writingMode: 'vertical-rl' }}>{label(stage)}</span>
            </button>
          );
        }
        return (
          <div key={stage} data-column={stage} className="w-[232px] max-[520px]:w-[78vw] shrink-0 flex flex-col min-h-0">
            <div className="flex items-center gap-2 px-1 pb-2.5 shrink-0">
              <StageGlyph stage={stage} ladder={stages} size={13} />
              <button type="button" data-fold={stage} aria-label={'Fold ' + label(stage)} title={stage + ' — click to fold'}
                onClick={() => toggleColumn(key)}
                className={`text-[13.5px] font-semibold truncate min-w-0 text-left hover:underline underline-offset-2 ${bad ? 'text-bad' : 'text-ink'}`}>{label(stage)}</button>
              <span className="text-[12px] text-muted tnum px-1.5 rounded-full bg-chrome">{list.length}</span>
            </div>
            <div
              className={`flex-1 min-h-[120px] overflow-y-auto rounded-[14px] p-2 space-y-2 transition-shadow ${over === stage ? 'ring-2 ring-[var(--border-focus)]' : ''}`}
              style={{ background: bad ? 'var(--tint-bad)' : 'rgba(230,226,217,.45)' }}
              data-scroll {...dropProps}>
              {list.map((c) => <Card key={c.id} c={c} selected={c.id === selectedId} landed={c.id === landed} draggable={!!onMove}
                onOpen={onOpen} onHold={(id) => { held.current = id; setDragging(!!id); }} />)}
              {!list.length && <div className="text-[12.5px] text-faint text-center py-6">{empty}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Card({ c, selected, landed, draggable, onOpen, onHold }: {
  c: BoardCard; selected: boolean; landed: boolean; draggable: boolean; onOpen: (id: string) => void; onHold: (id: string | null) => void;
}) {
  const [dragging, setDrag] = useState(false);
  const fields = c.fields.slice(0, 3);
  return (
    <button type="button" data-card-id={c.id} draggable={draggable}
      onClick={() => onOpen(c.id)}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', c.id);
        onHold(c.id);
        setTimeout(() => setDrag(true), 0);
      }}
      onDragEnd={() => { setDrag(false); onHold(null); }}
      className={`w-full text-left rounded-[12px] bg-card p-3 block transition-[box-shadow,opacity] ${dragging ? 'opacity-40' : ''} ${landed ? 'ring-2 ring-[var(--border-focus)]' : ''}`}
      style={{
        border: selected ? '1.5px solid var(--text-primary)' : c.alert ? '1px solid var(--bad)' : '1px solid var(--border-primary)',
        boxShadow: selected ? 'var(--shadow-lg)' : 'var(--shadow-sm)',
      }}>
      <div className="flex items-center gap-2 min-w-0">
        {c.colour && <Dot colour={c.colour} size={8} />}
        <span className="text-[14px] font-semibold text-ink truncate">{c.title}</span>
      </div>
      {fields.length > 0 && (
        <div className="mt-2 space-y-1.5 text-[12.5px] text-ink2">
          {fields.map((f, i) => {
            const Icon = f.icon;
            return (
              <div key={i} className={`flex items-start gap-2 leading-[17px] ${f.tone === 'warn' ? 'text-warn' : f.tone === 'bad' ? 'text-bad' : f.tone === 'good' ? 'text-good' : ''}`}>
                {f.who !== undefined ? <Avatar name={f.who} size={18} /> : Icon ? <Icon size={14} className="text-faint shrink-0 mt-[1px]" /> : null}
                <span className="min-w-0 break-words">{f.text}</span>
              </div>
            );
          })}
        </div>
      )}
    </button>
  );
}
