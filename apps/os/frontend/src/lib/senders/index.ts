/* The cold email checks: the sending tool's spintax and merge fields, then the general
 * checks every email gets (spam words, links per email, words per email).
 *
 * The text comes in blocks, one per paragraph or heading, so a flag points back into the
 * editor: { block, from, to } are offsets inside one block's text. Fix all returns edits in
 * the same terms, and the editor applies them as one step (one undo).
 *
 * Fix all converts spintax and merge fields to the tool's form, fixes the spacing and the case of
 * the tool's standard field names, and closes braces around a known name. It never guesses an
 * unknown field name: those stay flagged. "Other" (or no tool) runs the general checks only.
 *
 * Imports carry .ts so tests/documents.test.mjs runs this file in Node as it is. */
import type { SenderRules } from './types.ts';
import { INSTANTLY } from './instantly.ts';
import { SMARTLEAD } from './smartlead.ts';
import { PLUSVIBE } from './plusvibe.ts';
import { countWords } from '../readability.ts';

export type { SenderRules };
export const TOOLS = ['Instantly', 'Smartlead', 'PlusVibe', 'Other'] as const;
export type Tool = (typeof TOOLS)[number];
export const RULES: Record<string, SenderRules> = { Instantly: INSTANTLY, Smartlead: SMARTLEAD, PlusVibe: PLUSVIBE };

/** A saved "Sending tool" value as one of the four: any other value (or none) is Other. */
export function toolOf(v: unknown): Tool {
  const x = String(v || '').trim().toLowerCase().replace(/[\s.-]/g, '');
  if (x === 'instantly' || x === 'instantlyai') return 'Instantly';
  if (x === 'smartlead' || x === 'smartleadai') return 'Smartlead';
  if (x === 'plusvibe' || x === 'plusvibeai' || x === 'pipl' || x === 'piplai') return 'PlusVibe';
  return 'Other';
}

export type FlagKind = 'spintax' | 'merge' | 'spaces' | 'braces' | 'multi' | 'unknown' | 'fallback' | 'spam' | 'links';
export interface Flag { block: number; from: number; to: number; kind: FlagKind; why: string; fixable: boolean }
export interface Edit { block: number; from: number; to: number; text: string }
export interface Block { text: string; heading?: boolean }
export interface EmailStat { block: number; title: string; words: number; links: number; spam: number }
export interface CopyCheck { flags: Flag[]; emails: EmailStat[]; fixes: Edit[] }

/** Aim: words in the body of one email, and links in one email. */
export const MAX_WORDS = 90;
export const MAX_LINKS = 1;

/** Words and phrases spam filters weigh against. Lower case, whole words. */
export const SPAM_WORDS = ['free', 'guarantee', 'guaranteed', 'act now', 'limited time', 'click here', 'buy now', 'order now',
  'risk-free', 'risk free', 'no risk', 'winner', 'congratulations', 'cash', 'urgent', 'no obligation', 'special offer',
  'earn money', 'make money', 'double your', 'extra income', '100%', 'best price', 'lowest price', 'cheap', 'discount',
  'save big', 'once in a lifetime', 'exclusive deal', 'amazing', 'miracle', 'incredible deal', 'instant', 'unlimited',
  'apply now', 'sign up free', 'call now', 'don\'t delete', 'this isn\'t spam', 'not spam', 'cancel at any time',
  'no credit check', 'credit card', 'billion', 'million dollars', 'giveaway', 'prize', 'bonus', 'promise you',
  'increase sales', 'increase traffic', 'dear friend', 'opportunity', 'hidden', 'what are you waiting for'];

/* ---------- parse brace groups ------------------------------------------------ */

interface Group {
  open: '{{' | '{' | '{%';
  close: string | null;
  from: number; to: number;
  innerFrom: number; inner: string;
  /** Closed by the wrong brace, or never closed. */
  broken: boolean;
}

/** The outermost brace groups of a text, and the places of closing braces with no opening one. */
function parse(text: string): { groups: Group[]; stray: number[] } {
  const groups: Group[] = [];
  const stray: number[] = [];
  const stack: Array<{ open: Group['open']; from: number }> = [];
  const done = (g: Group) => { if (!stack.length) groups.push(g); };
  let i = 0;
  while (i < text.length) {
    const two = text.slice(i, i + 2);
    if (two === '{%' || two === '{{') { stack.push({ open: two, from: i }); i += 2; continue; }
    if (text[i] === '{') { stack.push({ open: '{', from: i }); i++; continue; }
    if (two === '%}' && stack.length && stack[stack.length - 1].open === '{%') {
      const s = stack.pop()!;
      done({ open: s.open, close: '%}', from: s.from, to: i + 2, innerFrom: s.from + 2, inner: text.slice(s.from + 2, i), broken: false });
      i += 2; continue;
    }
    if (text[i] === '}') {
      if (!stack.length) { stray.push(i); i++; continue; }
      const s = stack[stack.length - 1];
      let len = 1, broken = false;
      if (s.open === '{{') { len = two === '}}' ? 2 : 1; broken = len === 1; }
      else if (s.open === '{') { if (two === '}}' && stack.length === 1) { len = 2; broken = true; } }
      else broken = true;
      stack.pop();
      const innerFrom = s.from + s.open.length;
      done({ open: s.open, close: text.slice(i, i + len), from: s.from, to: i + len, innerFrom, inner: text.slice(innerFrom, i), broken });
      i += len; continue;
    }
    i++;
  }
  if (stack.length) {
    const s = stack[0];
    const sp = text.slice(s.from).search(/\s/);
    const to = sp < 0 ? text.length : s.from + sp;
    const innerFrom = s.from + s.open.length;
    groups.push({ open: s.open, close: null, from: s.from, to, innerFrom, inner: text.slice(innerFrom, to), broken: true });
  }
  return { groups, stray };
}

/** Split on "|" outside any inner braces: [start, end) inside `s`. */
function splitBar(s: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  let depth = 0, start = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '{') depth++;
    else if (s[i] === '}') depth = Math.max(0, depth - 1);
    else if (s[i] === '|' && depth === 0) { out.push([start, i]); start = i + 1; }
  }
  out.push([start, s.length]);
  return out;
}

type Shape =
  | { type: 'liquid' } | { type: 'text' } | { type: 'broken'; name: string }
  | { type: 'merge'; name: string; nameAt: number; fallback: string | null }
  | { type: 'name1'; name: string }
  | { type: 'spintax'; form: 'random' | 'single'; options: Array<[number, number]> };

const NAME = /^\s*[A-Za-z][\w .-]*\s*$/;

function shape(g: Group): Shape {
  if (g.open === '{%') return g.broken ? { type: 'broken', name: '' } : { type: 'liquid' };
  if (g.broken) return { type: 'broken', name: g.inner.replace(/[{}]/g, '') };
  const parts = splitBar(g.inner);
  if (g.open === '{{') {
    const head = g.inner.slice(parts[0][0], parts[0][1]);
    if (parts.length > 1 && /^\s*random\s*$/i.test(head)) return { type: 'spintax', form: 'random', options: parts.slice(1) };
    return { type: 'merge', name: head, nameAt: 0, fallback: parts.length > 1 ? g.inner.slice(parts[1][0]) : null };
  }
  if (parts.length > 1) return { type: 'spintax', form: 'single', options: parts };
  return NAME.test(g.inner) ? { type: 'name1', name: g.inner } : { type: 'text' };
}

const norm = (name: string) => name.toLowerCase().replace(/[\s_.-]/g, '');
/** The tool's own spelling of a standard field, or null. */
function known(R: SenderRules, name: string): string | null {
  const n = norm(name);
  return R.fields.find((f) => norm(f) === n) || null;
}
const caseOk = (R: SenderRules, name: string) => (R.mergeCase === 'camel' ? !/_/.test(name) : !/[A-Z]/.test(name));

/* ---------- render: a group as the tool wants it ------------------------------- */

function mergeText(R: SenderRules, name: string, fallback: string | null): string {
  if (fallback === null) return '{{' + name + '}}';
  return '{{' + name + (R.fallback ? ' | ' + fallback.trim() : '|' + fallback) + '}}';
}

/** A text with every brace group in the tool's form. */
export function fixText(text: string, R: SenderRules): string {
  const { groups } = parse(text);
  let out = '';
  let at = 0;
  groups.forEach((g) => { out += text.slice(at, g.from) + render(text.slice(g.from, g.to), g, R); at = g.to; });
  return out + text.slice(at);
}

function render(raw: string, g: Group, R: SenderRules): string {
  const s = shape(g);
  switch (s.type) {
    case 'broken': { const k = known(R, s.name); return k ? '{{' + k + '}}' : raw; }
    case 'merge': {
      const k = known(R, s.name);
      return mergeText(R, k || s.name.trim(), s.fallback);
    }
    case 'name1': { const k = known(R, s.name); return k ? '{{' + k + '}}' : raw; }
    case 'spintax': {
      const opts = s.options.map(([a, b]) => fixText(g.inner.slice(a, b), R).trim());
      return R.spintax === 'random' ? '{{RANDOM | ' + opts.join(' | ') + '}}' : '{' + opts.join('|') + '}';
    }
    default: return raw;
  }
}

/* ---------- flags ------------------------------------------------------------------ */

function flagsIn(text: string, base: number, block: number, R: SenderRules | null, out: Flag[]): void {
  const { groups, stray } = parse(text);
  stray.forEach((i) => out.push({ block, from: base + i, to: base + i + 1, kind: 'braces', why: 'A closing brace with no opening one.', fixable: false }));
  groups.forEach((g) => {
    const s = shape(g);
    const at = (a: number, b: number) => ({ block, from: base + a, to: base + b });
    const raw = text.slice(g.from, g.to);
    const before = out.length;
    if (s.type === 'broken') {
      const k = R ? known(R, s.name) : null;
      out.push({ ...at(g.from, g.to), kind: 'braces', fixable: !!k,
        why: 'Unbalanced braces.' + (k ? ' Fix all writes {{' + k + '}}.' : ' Close them, or remove the stray one.') });
      return;
    }
    if (!R) return;
    if (s.type === 'merge') {
      const name = s.name;
      const k = known(R, name);
      /* "{{firstName | there}}": the space before the bar belongs to the bar, not the name. */
      const spaced = s.fallback === null ? name !== name.trim() : /^\s/.test(name);
      if (k && k !== name.trim()) out.push({ ...at(g.from, g.to), kind: 'merge', fixable: true, why: R.tool + ' writes this field {{' + k + '}}' + (spaced ? ', with no spaces inside the braces.' : '.') });
      else if (spaced) out.push({ ...at(g.from, g.to), kind: 'spaces', fixable: true, why: 'Spaces inside the braces. Write {{' + (k || name.trim()) + '}}.' });
      if (!k) {
        out.push({ ...at(g.from, g.to), kind: 'unknown', fixable: false,
          why: '"' + name.trim() + '" is not a standard ' + R.tool + ' field. Check the lead list has this column' +
            (caseOk(R, name.trim()) ? '.' : ', and that it is written ' + (R.mergeCase === 'camel' ? 'likeThis' : 'like_this') + '.') });
      }
      if (s.fallback === null && R.needFallbackOnFirstName && norm(name) === 'firstname') {
        out.push({ ...at(g.from, g.to), kind: 'fallback', fixable: false, why: 'No fallback: a lead with no first name gets an empty gap. Write {{' + (k || name.trim()) + ' | there}}.' });
      }
      if (s.fallback !== null && !R.fallback) {
        out.push({ ...at(g.from, g.to), kind: 'merge', fixable: false, why: R.tool + ' may not support a fallback after a bar. Check it in ' + R.tool + '.' });
      }
    } else if (s.type === 'name1') {
      const k = known(R, s.name);
      out.push({ ...at(g.from, g.to), kind: k ? 'merge' : 'braces', fixable: !!k,
        why: k ? (R.spintax === 'single' ? 'Single braces make spintax by mistake. Write {{' + k + '}}.' : 'Merge fields need double braces: {{' + k + '}}.')
          : 'Single braces around one word. A merge field needs {{ }}; spintax needs a bar: {a|b}.' });
    } else if (s.type === 'spintax') {
      if (s.form !== R.spintax) {
        out.push({ ...at(g.from, g.to), kind: 'spintax', fixable: true,
          why: R.tool + ' writes spintax ' + (R.spintax === 'random' ? '{{RANDOM | a | b}}' : '{a|b}') + '.' });
      }
      const opts = s.options.map(([a, b]) => g.inner.slice(a, b));
      if (s.form === 'single' && R.spintax === 'single' && opts.some((o) => o !== o.trim())) {
        out.push({ ...at(g.from, g.to), kind: 'spaces', fixable: true, why: 'Spaces next to the braces or bars become part of the email.' });
      }
      if (!R.emptyOption && opts.some((o) => !o.trim())) out.push({ ...at(g.from, g.to), kind: 'spintax', fixable: false, why: R.tool + ' may not accept an empty option.' });
      if (R.oneVariablePerSpintax) {
        const vars = opts.reduce((n, o) => n + parse(o).groups.filter((x) => { const t = shape(x).type; return t === 'merge' || t === 'name1'; }).length, 0);
        if (vars > 1) out.push({ ...at(g.from, g.to), kind: 'multi', fixable: false, why: R.tool + ' allows one merge field in one spintax block. This one has ' + vars + '.' });
      }
      s.options.forEach(([a, b]) => flagsIn(g.inner.slice(a, b), base + g.innerFrom + a, block, R, out));
    }
    /* Anything Fix all would change, with no fixable flag to say so, is spacing. */
    if (render(raw, g, R) !== raw && !out.slice(before).some((f) => f.fixable)) {
      out.push({ ...at(g.from, g.to), kind: 'spaces', fixable: true, why: 'Spacing differs from ' + R.tool + '\'s form. Fix all tidies it.' });
    }
  });
}

/* ---------- emails, links, spam ------------------------------------------------------ */

const EMAIL_START = /^\s*(email|e-mail|step|follow[- ]?up)\s*#?\s*\d+\b/i;
const SUBJECT = /^\s*(subject( line)?|preview( text)?)\s*:/i;
const LINK = /\b(?:https?:\/\/|www\.)[^\s)>\]]+/gi;

function spamIn(text: string): Array<[number, number, string]> {
  const lower = text.toLowerCase();
  const out: Array<[number, number, string]> = [];
  SPAM_WORDS.forEach((w) => {
    const re = new RegExp('(?<![\\p{L}\\p{N}])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\p{L}\\p{N}])', 'gu');
    let m: RegExpExecArray | null;
    while ((m = re.exec(lower))) out.push([m.index, m.index + m[0].length, w]);
  });
  return out;
}

export function checkCopy(blocks: Block[], tool: Tool | string): CopyCheck {
  const R = RULES[tool] || null;
  const flags: Flag[] = [];
  const fixes: Edit[] = [];
  const emails: EmailStat[] = [];
  const links: Array<Array<[number, number, number]>> = [];

  blocks.forEach((b, block) => {
    const text = b.text;
    /* A heading, or a line such as "Email 2", starts the next email. */
    const starts = !!b.heading || EMAIL_START.test(text);
    if (!emails.length || starts) {
      emails.push({ block, title: starts ? text.trim().slice(0, 60) : 'The email', words: 0, links: 0, spam: 0 });
      links.push([]);
    }
    const e = emails[emails.length - 1];
    flagsIn(text, 0, block, R, flags);
    if (R) {
      parse(text).groups.forEach((g) => {
        const raw = text.slice(g.from, g.to);
        const fixed = render(raw, g, R);
        if (fixed !== raw) fixes.push({ block, from: g.from, to: g.to, text: fixed });
      });
    }
    if (!starts && !SUBJECT.test(text)) e.words += countWords(text);
    let m: RegExpExecArray | null;
    LINK.lastIndex = 0;
    while ((m = LINK.exec(text))) { e.links++; links[links.length - 1].push([block, m.index, m.index + m[0].length]); }
    spamIn(text).forEach(([a, z, w]) => {
      e.spam++;
      flags.push({ block, from: a, to: z, kind: 'spam', fixable: false, why: '"' + w + '" is a spam word: filters may send the email to spam.' });
    });
  });

  /* Links: past the aim, mark every link in that email. */
  emails.forEach((e, i) => {
    if (e.links <= MAX_LINKS) return;
    links[i].forEach(([block, from, to]) => flags.push({ block, from, to, kind: 'links', fixable: false,
      why: e.links + ' links in this email. Aim for ' + MAX_LINKS + ' or none: links hurt delivery.' }));
  });

  flags.sort((p, q) => p.block - q.block || p.from - q.from);
  return { flags, emails, fixes };
}

/** Fix all on plain text blocks (the editor applies the same edits as one step). */
export function applyEdits(blocks: string[], edits: Edit[]): string[] {
  const out = blocks.slice();
  edits.slice().sort((p, q) => q.block - p.block || q.from - p.from).forEach((e) => {
    out[e.block] = out[e.block].slice(0, e.from) + e.text + out[e.block].slice(e.to);
  });
  return out;
}
