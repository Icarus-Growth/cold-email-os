import React from 'react';
import { ChevronRight, X } from 'lucide-react';
import { Sections, type SectionSpec } from './Section';
import { IconButton } from './Button';
import { Dot } from './Tag';
import { shortStage } from '../lib/format';
import { useEscapeLayer } from './escape';

export interface RecordPanelProps {
  /** Small line above the title, e.g. "Campaigns". */
  crumb?: string;
  /** What follows the crumb's chevron ("Campaigns > Spring launch"). Default: the title, when it is text.
   *  With nothing to follow, no chevron is drawn. */
  crumbRef?: string;
  title: React.ReactNode;
  /** Line under the title, e.g. "20 - Generate Playbook · in this stage for 3d". */
  sub?: React.ReactNode;
  /** The client's colour, shown as a square before the title. */
  colour?: string;
  /** With `stage`, draws the step bar (Step 3 of 9). */
  ladder?: readonly string[];
  stage?: string;
  /** Top-right, before the close button (doctrine: "Delete record" lives here and nowhere else). */
  actions?: React.ReactNode;
  onClose: () => void;
  /** Basic Details first, then one group per stage, then For Devs Only. */
  sections: Array<SectionSpec | null | undefined | false>;
  children?: React.ReactNode;
}

/** The record panel: floats on the right at ~38% of the page (480–760px), full width on phones.
 *  Escape closes it. Its body scrolls on its own and keeps its place when the data updates. */
export function RecordPanel({ crumb, crumbRef, title, sub, colour, ladder, stage, actions, onClose, sections, children }: RecordPanelProps) {
  // Escape closes it last, after any confirm box, drill list, drawer, phone menu or form
  // (ui/escape.ts). Escape inside a text box leaves the box, not the record.
  useEscapeLayer('panel', onClose);

  const at = ladder && stage ? ladder.indexOf(stage) : -1;
  const after = crumbRef || (typeof title === 'string' ? title : '');
  return (
    <aside role="dialog" aria-label={typeof title === 'string' ? title : 'Record'} data-record-panel
      className="fixed z-40 top-2 right-2 bottom-2 w-[clamp(480px,38vw,760px)] max-w-[calc(100vw-16px)] max-[720px]:inset-0 max-[720px]:w-full max-[720px]:max-w-none max-[720px]:rounded-none rounded-[14px] bg-card border border-line shadow-[var(--shadow-xl)] flex flex-col overflow-hidden">
      <div className="px-5 pt-3.5 pb-3 border-b border-line2 shrink-0">
        <div className="flex items-center gap-1.5 text-[12px] text-muted min-h-[30px]">
          {crumb && <span data-crumb className="flex items-center gap-1.5 min-w-0">
            <span className="shrink-0">{crumb}</span>
            {after && <><ChevronRight size={11} className="shrink-0" /><span className="text-ink2 truncate">{after}</span></>}
          </span>}
          <span className="ml-auto flex items-center gap-1.5">{actions}<IconButton icon={X} label="Close the record" onClick={onClose} /></span>
        </div>
        <h2 className="font-display text-[20px] leading-[28px] font-semibold text-ink mt-1 flex items-center gap-2 break-words">
          {colour && <Dot colour={colour} size={10} />}{title}
        </h2>
        {sub && <div className="text-[12.5px] text-muted mt-0.5">{sub}</div>}
        {ladder && at > -1 && (
          <div className="mt-2.5">
            <div className="flex gap-1" aria-hidden>
              {ladder.map((s, i) => (
                <span key={s} className="h-[4px] flex-1 rounded-full"
                  style={{ background: i < at ? 'var(--good)' : i === at ? 'var(--text-primary)' : 'var(--border-primary)' }} />
              ))}
            </div>
            <div className="flex justify-between text-[10.5px] text-faint mt-1 gap-2">
              <span>{shortStage(ladder[0])}</span>
              <span className="text-ink font-medium text-center">Step {at + 1} of {ladder.length}: {shortStage(stage)}</span>
              <span>{shortStage(ladder[ladder.length - 1])}</span>
            </div>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4" data-scroll>
        <Sections sections={sections} />
        {children}
      </div>
    </aside>
  );
}

/** A record shown as a page (a table row opens one: client, team member, form submission).
 *  The page header already carries the title; this adds the sub line, a badge, actions and the sections. */
export function RecordPage({ sub, badge, actions, sections, children }: {
  sub?: React.ReactNode; badge?: React.ReactNode; actions?: React.ReactNode;
  sections: Array<SectionSpec | null | undefined | false>; children?: React.ReactNode;
}) {
  return (
    <div className="max-w-[920px] rounded-[14px] bg-card border border-line shadow-[var(--shadow-sm)]" data-record-page>
      {(sub || badge || actions) && (
        <div className="px-6 py-3.5 border-b border-line2 flex items-center gap-3 flex-wrap">
          {badge}
          {sub && <div className="text-[13px] text-muted min-w-0">{sub}</div>}
          {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="px-6 py-5 max-[520px]:px-4"><Sections sections={sections} />{children}</div>
    </div>
  );
}
