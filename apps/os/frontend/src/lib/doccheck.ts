/* The one extra line per agency type, under the readability numbers (agency.config.ts names the
 * check on each document field):
 *   ad-script   read-aloud time against 15, 30 and 60 second ads
 *   caption     caption length against the platform's limit
 *   email-copy  subject line and preview text length
 * (cold-email has its own part: lib/senders.)
 *
 * No imports: tests/documents.test.mjs runs this file in Node as it is. */

export type DocCheck = 'cold-email' | 'ad-script' | 'caption' | 'email-copy';
export interface Line { text: string; tone: 'good' | 'warn' | 'bad' | null }

/** Spoken words a second in an ad read (150 a minute). */
export const SPOKEN_PER_SECOND = 2.5;
export const AD_LENGTHS = [15, 30, 60];

export function adScript(words: number): Line[] {
  const secs = Math.round(words / SPOKEN_PER_SECOND);
  const fits = AD_LENGTHS.filter((l) => secs <= l);
  return [{ text: 'Read aloud: about ' + secs + ' s (' + words + ' words at 150 a minute).', tone: null },
    { text: AD_LENGTHS.map((l) => l + ' s ad: ' + (secs <= l ? 'fits' : 'too long')).join(' · '), tone: fits.length ? (secs <= AD_LENGTHS[0] ? 'good' : null) : 'bad' }];
}

/** Caption limits, in characters. */
export const CAPTION_LIMITS: Array<[string, RegExp, number]> = [
  ['Instagram', /insta|^ig$|reels?/i, 2200], ['TikTok', /tik\s*tok/i, 4000], ['YouTube', /you\s*tube|shorts/i, 5000],
  ['LinkedIn', /linked\s*in/i, 3000], ['Facebook', /facebook|^fb$/i, 63206], ['X', /^x$|twitter/i, 280],
  ['Threads', /threads/i, 500], ['Pinterest', /pinterest/i, 500],
];

export function caption(text: string, platform: unknown): Line[] {
  const n = text.length;
  const p = String(platform || '');
  const hit = CAPTION_LIMITS.filter(([, re]) => p.split(/[,/&]| and /).some((x) => re.test(x.trim())));
  const list = hit.length ? hit : CAPTION_LIMITS.filter(([name]) => ['Instagram', 'TikTok', 'LinkedIn', 'X'].indexOf(name) > -1);
  const out: Line[] = [{ text: n.toLocaleString() + ' characters' + (hit.length ? '' : ' (no platform on the card: the main limits below)') + '.', tone: null }];
  list.forEach(([name, , max]) => out.push({ text: name + ': ' + n.toLocaleString() + ' of ' + max.toLocaleString() + (n > max ? ', ' + (n - max).toLocaleString() + ' too many' : ''), tone: n > max ? 'bad' : 'good' }));
  if (list.some(([name]) => name === 'Instagram') && n > 125) out.push({ text: 'Instagram shows the first 125 characters before "more". Put the hook there.', tone: null });
  return out;
}

/** Subject lines over this get cut on a phone; preview text works best in this range. */
export const SUBJECT_MAX = 50;
export const PREVIEW_MIN = 40;
export const PREVIEW_MAX = 90;

export function emailCopy(blocks: string[]): Line[] {
  const out: Line[] = [];
  blocks.forEach((b) => {
    const m = /^\s*(subject(?: line)?|preview(?: text)?)\s*:\s*(.*)$/i.exec(b);
    if (!m) return;
    const value = m[2].trim();
    const n = value.length;
    if (/^subject/i.test(m[1])) {
      out.push({ text: 'Subject "' + (n > 40 ? value.slice(0, 40) + '…' : value) + '": ' + n + ' characters' + (n > SUBJECT_MAX ? ', over ' + SUBJECT_MAX + ': phones cut it' : ''), tone: n > SUBJECT_MAX ? 'warn' : n ? 'good' : 'bad' });
    } else {
      const ok = n >= PREVIEW_MIN && n <= PREVIEW_MAX;
      out.push({ text: 'Preview text: ' + n + ' characters (aim ' + PREVIEW_MIN + ' to ' + PREVIEW_MAX + ')', tone: ok ? 'good' : 'warn' });
    }
  });
  if (!out.length) out.push({ text: 'Write "Subject:" and "Preview text:" lines to check their length.', tone: null });
  return out;
}
