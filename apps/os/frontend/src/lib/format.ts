/* The small formatters every screen uses. */

const DAY = 86400000;

/** Whole hours since a timestamp (null when there is none). */
export function hoursSince(ts?: string | null): number | null {
  if (!ts) return null;
  return Math.floor((Date.now() - new Date(ts).getTime()) / 3600000);
}
/** Whole days since a timestamp (null when there is none). */
export function daysSince(ts?: string | null): number | null {
  if (!ts) return null;
  return Math.floor((Date.now() - new Date(ts).getTime()) / DAY);
}
/** "just now" / "5h" / "3d" — how long something has waited. */
export function wait(ts?: string | null): string {
  const hrs = hoursSince(ts);
  if (hrs === null) return '—';
  if (hrs < 1) return 'just now';
  if (hrs < 24) return hrs + 'h';
  return Math.floor(hrs / 24) + 'd';
}
/** "just now" / "5h ago" / "3d ago" (empty when there is no timestamp). */
export function ago(ts?: string | null): string {
  const w = wait(ts);
  return w === '—' ? '' : w === 'just now' ? w : w + ' ago';
}
/** "04 Oct". */
export function dateShort(ts?: string | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}
/** "04 Oct 2026". */
export function dateLong(ts?: string | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}
/** "04 Oct 2026 14:05". */
export function stamp(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}
/** "03 Oct 2026, 09:00" (a filing time: the date and the time). */
export function dateTime(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ', ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}
/** Yes / No / —. */
export function yesNo(v: unknown): string { return v === true ? 'Yes' : v === false ? 'No' : '—'; }
/** The value as text, or — when empty. */
export function text(v: unknown): string { return v === null || v === undefined || v === '' ? '—' : String(v); }
/** "Morgan Test" -> "MT". */
export function initials(name?: string | null): string {
  if (!name) return '?';
  const p = String(name).trim().split(/\s+/);
  return (p[0][0] + (p[1] ? p[1][0] : '')).toUpperCase();
}
/** "20 - Copywriting" -> "Copywriting", "-1 - Rejected" -> "Rejected". */
export function shortStage(stage?: string | null): string {
  return String(stage || '').replace(/^-?\d+\s-\s/, '');
}
/** The number of a stage: "29 - Amendments" -> 29 (null when it has none). */
export function stageNumber(stage?: string | null): number | null {
  const m = /^(-?\d+) - /.exec(String(stage || ''));
  return m ? Number(m[1]) : null;
}
/** "drive_folder_url" -> "Drive folder url" (the readable name of a raw column). */
export function readable(key: string): string {
  const t = String(key).replace(/_id$/, '').replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}
/** Seconds as "m:ss" (null when there is nothing to show). */
export function duration(secs: unknown): string | null {
  if (secs === null || secs === undefined || secs === '' || isNaN(Number(secs))) return null;
  const s = Number(secs);
  return Math.floor(s / 60) + ':' + ('0' + Math.round(s % 60)).slice(-2);
}
function pad2(n: number) { return ('0' + n).slice(-2); }
/** A timestamp as the local wall-clock string a datetime-local box expects ("2026-10-14T09:00"). */
export function localStamp(ts?: string | null): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '';
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + 'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}
/** 'YYYY-MM-DD' of a moment, in the viewer's own time zone. */
export function dayKey(d: Date | string | number): string {
  const x = d instanceof Date ? d : new Date(d);
  return x.getFullYear() + '-' + pad2(x.getMonth() + 1) + '-' + pad2(x.getDate());
}
/** A due date (a day or a timestamp) as one card line: "Late since 08 Oct" (red), "Due today" (amber),
 *  "Due 15 Oct". Null when there is no date. A day is late only once it is over.
 *  canBeLate false (a finished card, or a live one): a past date is a plain "Due 08 Oct", never late. */
export function dueLine(v?: string | null, label = 'Due', canBeLate = true): { text: string; tone: 'bad' | 'warn' | null; late: boolean } | null {
  if (!v) return null;
  const s = String(v);
  const isDay = /^\d{4}-\d{2}-\d{2}$/.test(s);
  const t = isDay ? new Date(s + 'T23:59:59').getTime() : new Date(s).getTime();
  if (isNaN(t)) return null;
  const day = isDay ? s : dayKey(t);
  const today = dayKey(new Date());
  if (t < Date.now() && !canBeLate) return { text: label + ' ' + dateShort(isDay ? s + 'T12:00:00' : s), tone: null, late: false };
  if (t < Date.now()) return { text: 'Late since ' + dateShort(isDay ? s + 'T12:00:00' : s), tone: 'bad', late: true };
  if (day === today) return { text: label + ' today', tone: 'warn', late: false };
  return { text: label + ' ' + dateShort(isDay ? s + 'T12:00:00' : s), tone: null, late: false };
}

export const fmt = { text, yesNo, wait, ago, dateShort, dateLong, dateTime, stamp, daysSince, hoursSince, initials, shortStage, stageNumber, readable,
                     duration, localStamp, dayKey, dueLine };
