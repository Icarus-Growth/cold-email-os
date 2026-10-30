/* Readability: our own code, in the browser, no network.
 *
 * The text comes in blocks (one per paragraph, heading or list item), so every mark can point
 * back into the editor: { block, from, to } are character offsets inside one block's text.
 *
 * Grade: the Automated Readability Index, 4.71 x letters per word + 0.5 x words per sentence
 *   - 21.43, rounded, never below 0. Aim for 9 or lower.
 * A sentence of 14 words or more is hard at grade 10 to 13, and very hard at grade 14 or more.
 * Merge fields and spintax ({{firstName}}, {a|b}) count as one word, with no letters.
 *
 * No imports: tests/documents.test.mjs runs this file in Node as it is. */

export type MarkKind = 'veryHard' | 'hard' | 'weak' | 'simpler';
export interface Mark { block: number; from: number; to: number; kind: MarkKind; why: string }

export interface Readability {
  grade: number;
  words: number;
  sentences: number;
  paragraphs: number;
  /** Letters and digits in words. */
  letters: number;
  /** Every character, spaces too (no line breaks). */
  characters: number;
  /** Silent reading time, at 238 words a minute. */
  readingSeconds: number;
  marks: Mark[];
  /** How many marks of each kind; hard and veryHard count sentences. */
  count: Record<MarkKind, number>;
}

/** The ARI grade for some letters, words and sentences (0 when there are no words). */
export function ariGrade(letters: number, words: number, sentences: number): number {
  if (!words || !sentences) return 0;
  return Math.max(0, Math.round(4.71 * (letters / words) + 0.5 * (words / sentences) - 21.43));
}

/** A brace group ({{...}}, {...} or {%...%}), outermost only, as [from, to). Unbalanced braces
 *  run to the end of the word. */
export function braceGroups(text: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  let depth = 0;
  let start = -1;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '{') { if (depth === 0) start = i; depth++; }
    else if (c === '}' && depth > 0) { depth--; if (depth === 0) out.push([start, i + 1]); }
  }
  if (depth > 0 && start > -1) { const sp = text.slice(start).search(/\s/); out.push([start, sp < 0 ? text.length : start + sp]); }
  return out;
}

/** Text with every brace group swapped for one word of the same length ("xxxx"), so offsets stay put. */
function maskGroups(text: string): string {
  let out = text;
  braceGroups(text).forEach(([a, b]) => { out = out.slice(0, a) + '\u0001'.repeat(b - a) + out.slice(b); });
  return out;
}

/** Words as the editor and the database count them: split on spaces, keep the parts with a
 *  letter or a digit; a merge field or a spintax block is one word. */
export function countWords(text: string): number {
  return maskGroups(text).split(/\s+/).filter((w) => /[\p{L}\p{N}\u0001]/u.test(w)).length;
}

interface Word { from: number; to: number; text: string; letters: number }
function wordsOf(masked: string, from: number, to: number): Word[] {
  const out: Word[] = [];
  const re = /[^\s]+/g;
  const part = masked.slice(from, to);
  let m: RegExpExecArray | null;
  while ((m = re.exec(part))) {
    const raw = m[0];
    if (!/[\p{L}\p{N}\u0001]/u.test(raw)) continue;
    const lead = raw.search(/[\p{L}\p{N}\u0001]/u);
    const core = raw.replace(/^[^\p{L}\p{N}\u0001]+|[^\p{L}\p{N}\u0001]+$/gu, '');
    out.push({ from: from + m.index + lead, to: from + m.index + lead + core.length, text: core,
      letters: (core.match(/[\p{L}\p{N}]/gu) || []).length });
  }
  return out;
}

/** The sentences of one block, as [from, to): split after . ! ? (and …) followed by a space. */
export function sentencesOf(text: string): Array<[number, number]> {
  const masked = maskGroups(text);
  const out: Array<[number, number]> = [];
  const re = /[.!?…]+["')\]”’]*(?=\s|$)/g;
  let start = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(masked))) {
    const end = m.index + m[0].length;
    if (/[\p{L}\p{N}\u0001]/u.test(masked.slice(start, end))) out.push([start, end]);
    start = end;
  }
  if (/[\p{L}\p{N}\u0001]/u.test(masked.slice(start))) out.push([start, masked.length]);
  return out.map(([a, b]) => {
    while (a < b && /\s/.test(text[a])) a++;
    while (b > a && /\s/.test(text[b - 1])) b--;
    return [a, b] as [number, number];
  });
}

/* ---------- word lists (one place to tune them) ------------------------------ */

/** Words that end in -ly and are not adverbs. */
const NOT_ADVERBS = new Set(('only family reply apply supply early daily weekly monthly yearly hourly likely unlikely holy july italy ugly ' +
  'belly fly rely ally bully jelly lovely lonely friendly costly lively silly smelly curly hilly chilly elderly orderly ' +
  'butterfly assembly anomaly melancholy monopoly rally sally tally italy wily oily wooly woolly jolly folly homely ' +
  'timely kindly deadly ghastly ghostly manly comely courtly stately scholarly leisurely heavenly worldly bodily ' +
  'multiply comply imply firefly dragonfly lily emily molly polly holly billy willy reilly kelly ally rely belly').split(' '));

/** Weak phrases: they add words and take away force. Longest first. */
const WEAK: Array<[string, string]> = [
  ['in order to', 'Weak phrase: "to" says the same.'],
  ['a lot of', 'Weak phrase: say how many, or use "many".'],
  ['kind of', 'Weak phrase: cut it.'], ['sort of', 'Weak phrase: cut it.'],
  ['i think', 'Weak phrase: say it, or cut it.'], ['i believe', 'Weak phrase: say it, or cut it.'], ['i feel', 'Weak phrase: say it, or cut it.'],
  ['it seems', 'Weak phrase: say it, or cut it.'], ['a bit', 'Weak phrase: cut it.'], ['a little', 'Weak phrase: cut it.'],
  ['very', 'Weak word: use a stronger word instead.'], ['really', 'Weak word: cut it, or use a stronger word.'],
  ['just', 'Weak word: cut it.'], ['quite', 'Weak word: cut it.'], ['rather', 'Weak word: cut it.'],
  ['somewhat', 'Weak word: cut it.'], ['basically', 'Weak word: cut it.'], ['actually', 'Weak word: cut it.'],
  ['literally', 'Weak word: cut it.'], ['maybe', 'Weak word: say it, or cut it.'], ['perhaps', 'Weak word: say it, or cut it.'],
  ['totally', 'Weak word: cut it.'], ['simply', 'Weak word: cut it.'], ['extremely', 'Weak word: use a stronger word instead.'],
];

/** Words with a simpler choice. */
export const SIMPLER: Record<string, string> = {
  utilize: 'use', utilise: 'use', utilization: 'use', approximately: 'about', assist: 'help', assistance: 'help',
  commence: 'start', demonstrate: 'show', facilitate: 'help', individual: 'person', individuals: 'people', obtain: 'get',
  purchase: 'buy', sufficient: 'enough', additional: 'more', numerous: 'many', subsequently: 'later', regarding: 'about',
  endeavor: 'try', endeavour: 'try', initiate: 'start', terminate: 'end', accomplish: 'do', acquire: 'get', inform: 'tell',
  require: 'need', requires: 'needs', provide: 'give', therefore: 'so', however: 'but', nevertheless: 'still', modify: 'change',
  objective: 'aim', optimum: 'best', optimal: 'best', permit: 'let', possess: 'have', request: 'ask', reside: 'live',
  transmit: 'send', visualize: 'see', brief: 'short', leverage: 'use', ascertain: 'find out', consequently: 'so',
  component: 'part', components: 'parts', currently: 'now', establish: 'set up', expedite: 'speed up', indicate: 'show',
  magnitude: 'size', methodology: 'method', participate: 'take part', prioritize: 'rank', remainder: 'rest',
  substantial: 'large', sufficiently: 'enough', capability: 'ability', consolidate: 'combine', anticipate: 'expect',
};

const BE = new Set(['am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', "isn't", "aren't", "wasn't", "weren't"]);
const IRREGULAR = new Set(('written done made given taken seen sent built known shown held chosen bought brought caught ' +
  'found got gotten kept left lost meant paid put read said sold spent stood told thought understood won begun broken ' +
  'driven eaten fallen forgotten forgiven frozen hidden ridden risen shaken spoken stolen sworn torn thrown woken worn ' +
  'drawn grown flown blown sung run hit cut set shut let hurt cost quit split spread led fed met sought taught dealt ' +
  'felt heard laid lent slept swept wept bound found ground wound struck stuck hung').split(' '));

function adverb(w: string): boolean {
  const x = w.toLowerCase();
  return x.length > 4 && x.endsWith('ly') && !NOT_ADVERBS.has(x);
}

/* ---------- analyse -------------------------------------------------------- */

export function analyze(blocks: string[]): Readability {
  const marks: Mark[] = [];
  let words = 0, sentences = 0, letters = 0, characters = 0, paragraphs = 0;
  const count: Record<MarkKind, number> = { veryHard: 0, hard: 0, weak: 0, simpler: 0 };

  blocks.forEach((text, block) => {
    characters += text.replace(/\n/g, '').length;
    const masked = maskGroups(text);
    const sents = sentencesOf(text);
    if (!sents.length) return;
    paragraphs++;
    const lower = masked.toLowerCase();
    sents.forEach(([a, b]) => {
      const ws = wordsOf(masked, a, b);
      if (!ws.length) return;
      const l = ws.reduce((n, w) => n + w.letters, 0);
      words += ws.length; letters += l; sentences++;
      const g = ariGrade(l, ws.length, 1);
      if (ws.length >= 14 && g >= 10) {
        const very = g >= 14;
        count[very ? 'veryHard' : 'hard']++;
        marks.push({ block, from: a, to: b, kind: very ? 'veryHard' : 'hard',
          why: (very ? 'Very hard to read' : 'Hard to read') + ': ' + ws.length + ' words, grade ' + g + '. Split it into shorter sentences, or cut words.' });
      }
      /* Weak phrases first (so "really" is not also an adverb), then adverbs, passive voice, simpler words. */
      const taken: Array<[number, number]> = [];
      const free = (x: number, y: number) => !taken.some(([p, q]) => x < q && y > p);
      WEAK.forEach(([phrase, why]) => {
        const re = new RegExp('(?<![\\p{L}\\p{N}\'])' + phrase.replace(/ /g, '\\s+') + '(?![\\p{L}\\p{N}\'])', 'gu');
        let m: RegExpExecArray | null;
        const part = lower.slice(a, b);
        while ((m = re.exec(part))) {
          const x = a + m.index, y = x + m[0].length;
          if (!free(x, y)) continue;
          taken.push([x, y]); count.weak++;
          marks.push({ block, from: x, to: y, kind: 'weak', why });
        }
      });
      ws.forEach((w, i) => {
        if (!free(w.from, w.to)) return;
        const x = w.text.toLowerCase();
        if (BE.has(x) && ws[i + 1]) {
          const next = ws[i + 1] && adverb(ws[i + 1].text) && ws[i + 2] ? ws[i + 2] : ws[i + 1];
          const p = next.text.toLowerCase();
          if ((p.length > 3 && p.endsWith('ed')) || IRREGULAR.has(p)) {
            taken.push([w.from, next.to]); count.weak++;
            marks.push({ block, from: w.from, to: next.to, kind: 'weak', why: 'Passive voice: say who does it ("we sent it", not "it was sent").' });
            return;
          }
        }
        if (adverb(w.text)) {
          taken.push([w.from, w.to]); count.weak++;
          marks.push({ block, from: w.from, to: w.to, kind: 'weak', why: 'Adverb: cut it, or use a stronger verb.' });
          return;
        }
        if (SIMPLER[x]) {
          taken.push([w.from, w.to]); count.simpler++;
          marks.push({ block, from: w.from, to: w.to, kind: 'simpler', why: 'Simpler word: "' + SIMPLER[x] + '".' });
        }
      });
    });
  });

  marks.sort((p, q) => p.block - q.block || p.from - q.from || (p.kind === 'veryHard' || p.kind === 'hard' ? -1 : 1));
  return { grade: ariGrade(letters, words, sentences), words, sentences, paragraphs, letters, characters,
    readingSeconds: Math.round((words / 238) * 60), marks, count };
}

/** Fewer words than this give no useful grade (ARI needs a few sentences). */
export const MIN_GRADE_WORDS = 20;
/** The grade as people read it: "Reading grade 7", or "Too short to grade" (not "Grade 0"). */
export function gradeLabel(r: Pick<Readability, 'grade' | 'words'>): string {
  return r.words < MIN_GRADE_WORDS ? 'Too short to grade' : 'Reading grade ' + r.grade;
}

/** "15 s", "2 min", "1 min 20 s". */
export function duration(seconds: number): string {
  if (seconds < 60) return Math.max(0, Math.round(seconds)) + ' s';
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return m + ' min' + (s ? ' ' + s + ' s' : '');
}
