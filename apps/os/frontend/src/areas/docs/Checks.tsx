/* The readability panel beside the editor: the grade and the counts, the marks (each kind can
 * be hidden), the one extra line of this agency type, and for cold email the sending-tool
 * checks with "Fix all". All of it runs in the browser on the text on screen: nothing is sent. */
import { Eye, EyeOff, Wand2 } from 'lucide-react';
import { Button, Select } from '../../ui';
import { duration, gradeLabel, MIN_GRADE_WORDS, type MarkKind, type Readability } from '../../lib/readability';
import { RULES, TOOLS, MAX_WORDS, MAX_LINKS, type CopyCheck, type Tool } from '../../lib/senders';
import type { Line } from '../../lib/doccheck';

/** The kinds a person can hide: the four readability marks and the cold email flags. */
export type HideKind = MarkKind | 'flags';

export const KINDS: Array<{ kind: HideKind; label: string; cls: string }> = [
  { kind: 'veryHard', label: 'Very hard sentences', cls: 'doc-mark-veryHard' },
  { kind: 'hard', label: 'Hard sentences', cls: 'doc-mark-hard' },
  { kind: 'weak', label: 'Adverbs, passive voice, weak phrases', cls: 'doc-mark-weak' },
  { kind: 'simpler', label: 'Simpler word exists', cls: 'doc-mark-simpler' },
];

const TONE: Record<string, string> = { good: 'text-[var(--text-success)]', warn: 'text-[var(--warn)]', bad: 'text-bad' };

function Stat({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="rounded-[10px] bg-ground px-2.5 py-1.5">
      <div className="text-[11px] text-muted">{k}</div>
      <div className="text-[14px] font-semibold text-ink tabular-nums">{typeof v === 'number' ? v.toLocaleString() : v}</div>
    </div>
  );
}

function Head({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted mt-5 mb-2">{children}</h3>;
}

function HideRow({ label, cls, count, hidden, onToggle }: { label: string; cls: string; count: number; hidden: boolean; onToggle: () => void }) {
  return (
    <li className="flex items-center gap-2 text-[12.5px]">
      <span className={`w-3 h-3 rounded-[3px] shrink-0 ${cls}`} aria-hidden />
      <span className={`flex-1 min-w-0 ${hidden ? 'text-faint line-through' : 'text-ink2'}`}>{label}</span>
      <span className="tabular-nums text-ink font-medium">{count}</span>
      <button type="button" onClick={onToggle} aria-pressed={!hidden} aria-label={(hidden ? 'Show ' : 'Hide ') + label.toLowerCase()}
        className="w-7 h-7 inline-flex items-center justify-center rounded-[8px] text-muted hover:bg-ground hover:text-ink">
        {hidden ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </li>
  );
}

export interface ChecksProps {
  r: Readability;
  hidden: Record<string, boolean>;
  onHide: (kind: HideKind) => void;
  /** The extra line(s) of this agency type, with its title. */
  extra: { title: string; lines: Line[] } | null;
  /** Cold email only. */
  cold: { check: CopyCheck; tool: Tool; onTool: (t: Tool) => void; onFixAll: () => void; onGo: (i: number) => void; canEdit: boolean } | null;
}

export function Checks({ r, hidden, onHide, extra, cold }: ChecksProps) {
  const tone = r.grade <= 9 ? 'good' : r.grade <= 12 ? 'warn' : 'bad';
  const short = r.words < MIN_GRADE_WORDS;
  const fixable = cold ? cold.check.fixes.length : 0;
  const left = cold ? cold.check.flags.filter((f) => !f.fixable).length : 0;
  return (
    <div className="text-[13px]" data-checks>
      <div className="flex items-baseline gap-2">
        <span className={`font-display font-semibold ${short ? 'text-[20px] leading-[30px] text-faint' : 'text-[24px] leading-[30px] ' + TONE[tone]}`} data-grade>{gradeLabel(r)}</span>
      </div>
      <p className="text-[12px] text-muted mt-0.5">{short ? 'The grade shows from ' + MIN_GRADE_WORDS + ' words. ' : ''}Aim for grade 9 or lower: most readers then read it in one pass.</p>

      <div className="grid grid-cols-3 gap-1.5 mt-3">
        <Stat k="Words" v={r.words} />
        <Stat k="Sentences" v={r.sentences} />
        <Stat k="Paragraphs" v={r.paragraphs} />
        <Stat k="Letters" v={r.letters} />
        <Stat k="Characters" v={r.characters} />
        <Stat k="Reading time" v={duration(r.readingSeconds)} />
      </div>

      {extra && <>
        <Head>{extra.title}</Head>
        <ul className="space-y-1" data-type-check>
          {extra.lines.map((l, i) => <li key={i} className={`text-[12.5px] ${l.tone ? TONE[l.tone] : 'text-ink2'}`}>{l.text}</li>)}
        </ul>
      </>}

      <Head>Marks</Head>
      <ul className="space-y-0.5">
        {KINDS.map((k) => <HideRow key={k.kind} label={k.label} cls={k.cls} count={r.count[k.kind as MarkKind]} hidden={!!hidden[k.kind]} onToggle={() => onHide(k.kind)} />)}
      </ul>
      <p className="text-[11.5px] text-faint mt-1.5">Click a marked word to see why it is marked.</p>

      {cold && <>
        <Head>Cold email checks</Head>
        <div className="text-[12px] text-muted mb-1">Sending tool</div>
        <Select aria-label="Sending tool" value={cold.tool} options={TOOLS.map((t): [string, string] => [t, t])} onChange={(v) => cold.onTool(v as Tool)} />
        <p className="text-[11.5px] text-faint mt-1">{RULES[cold.tool] ? 'Rules from ' + RULES[cold.tool].source + '.' : 'No tool rules: only the general checks run (braces, spam words, links, length).'}</p>

        <ul className="mt-2.5 space-y-0.5" data-emails>
          {cold.check.emails.map((e, i) => (
            <li key={i} className="flex items-center gap-2 text-[12.5px]">
              <span className="flex-1 min-w-0 truncate text-ink2">{e.title}</span>
              <span className={`tabular-nums ${e.words > MAX_WORDS ? 'text-bad' : 'text-muted'}`}>{e.words} words</span>
              <span className={`tabular-nums ${e.links > MAX_LINKS ? 'text-bad' : 'text-muted'}`}>{e.links} {e.links === 1 ? 'link' : 'links'}</span>
            </li>
          ))}
        </ul>
        <p className="text-[11.5px] text-faint mt-1">Aim for {MAX_WORDS} words or fewer an email, and {MAX_LINKS} link or none.</p>

        <ul className="mt-2.5 space-y-0.5">
          <HideRow label="Flags" cls="doc-flag-key" count={cold.check.flags.length} hidden={!!hidden.flags} onToggle={() => onHide('flags')} />
        </ul>
        {cold.check.flags.length > 0 && (
          <ol className="mt-1.5 space-y-1 max-h-[260px] overflow-y-auto pr-1" data-flags>
            {cold.check.flags.map((f, i) => (
              <li key={i}>
                <button type="button" onClick={() => cold.onGo(i)} className="w-full text-left text-[12px] leading-[17px] rounded-[8px] px-2 py-1.5 hover:bg-ground">
                  <span className={f.fixable ? 'text-ink2' : 'text-bad'}>{f.why}</span>
                  {f.fixable && <span className="text-faint"> Fix all corrects it.</span>}
                </button>
              </li>
            ))}
          </ol>
        )}
        {cold.canEdit && fixable > 0 && (
          <Button size="sm" variant="primary" icon={Wand2} className="mt-2.5" onClick={cold.onFixAll}>Fix all ({fixable})</Button>
        )}
        {left > 0 && <p className="text-[11.5px] text-faint mt-1.5">Fix all does not guess field names, spam words, links or length: change those by hand.</p>}
      </>}
    </div>
  );
}
