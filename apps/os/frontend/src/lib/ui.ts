/* Page state that is not data: toasts, the confirm box, the per-screen filters,
 * the phone menu and the "New X" form.
 * The shell renders all of these; screens only call the functions below. */
import { tinyStore } from './tinyStore';

/* ---------- toasts ------------------------------------------------------- */

export type Tone = 'good' | 'bad' | null;
export interface ToastItem { id: number; text: string; tone: Tone }

export const toasts = tinyStore<ToastItem[]>([]);
let toastId = 0;

/** Show a short note. 'bad' notes stay until dismissed; the rest go after 5s. */
export function toast(text: string, tone: Tone = null): void {
  const id = ++toastId;
  toasts.set((list) => list.filter((t) => t.text !== text).concat([{ id, text, tone }]).slice(-4));
  if (tone !== 'bad') setTimeout(() => dismissToast(id), 5000);
}
/** Remove one note. */
export function dismissToast(id: number): void { toasts.set((list) => list.filter((t) => t.id !== id)); }

/* ---------- "Are you sure?" --------------------------------------------- */

export interface ConfirmSpec { title: string; body: string; verb: string; run: () => void }
export const confirmBox = tinyStore<ConfirmSpec | null>(null);
/** Ask before anything that hides or removes data. `run` fires on the red button. */
export function confirm(spec: ConfirmSpec): void { confirmBox.set(spec); }

/* ---------- per-screen filters (saved in this browser) --------------------
 * Keyed "<screen>:<name>" ("tasks:client", "team:status"). A value is one choice or a
 * list of ticked choices. */

export type ScreenFilterValue = string | string[];
const SCREEN_FILTER_KEY = 'os-screen-filters';

function loadScreenFilters(): Record<string, ScreenFilterValue> {
  try { const v = JSON.parse(localStorage.getItem(SCREEN_FILTER_KEY) || 'null'); return v && typeof v === 'object' ? v : {}; }
  catch { return {}; }
}
function persistScreen(v: Record<string, ScreenFilterValue>) { try { localStorage.setItem(SCREEN_FILTER_KEY, JSON.stringify(v)); } catch { /* private window */ } }

export const screenFilters = tinyStore<Record<string, ScreenFilterValue>>(loadScreenFilters());
/** Set one per-screen filter, keyed "<screen>:<name>". */
export function setScreenFilter(key: string, value: ScreenFilterValue): void {
  screenFilters.set((f) => { const n = { ...f, [key]: value }; persistScreen(n); return n; });
}
/** Tick or untick one value of a multi-choice filter. */
export function toggleScreenFilter(key: string, value: string): void {
  screenFilters.set((f) => {
    const cur = Array.isArray(f[key]) ? (f[key] as string[]) : [];
    const n = { ...f, [key]: cur.indexOf(value) > -1 ? cur.filter((v) => v !== value) : cur.concat([value]) };
    persistScreen(n);
    return n;
  });
}
/** Clear every filter of one screen (keys that start with "<screen>:"). */
export function clearScreenFilters(screen: string): void {
  screenFilters.set((f) => {
    const n: Record<string, ScreenFilterValue> = {};
    Object.keys(f).forEach((k) => { if (k.indexOf(screen + ':') !== 0) n[k] = f[k]; });
    persistScreen(n);
    return n;
  });
}
/** One choice, or `first` when nothing is set. */
export function filterValue(f: Record<string, ScreenFilterValue>, key: string, first: string): string {
  const v = f[key];
  return typeof v === 'string' ? v : first;
}
/** The ticked choices of a multi-choice filter. */
export function filterValues(f: Record<string, ScreenFilterValue>, key: string): string[] {
  const v = f[key];
  return Array.isArray(v) ? v : [];
}

/* ---------- shell toggles ----------------------------------------------- */

export const navOpen = tinyStore(false);
/** The "New X" form that is open: a table name, or 'team' for "Add team member". */
export const createOpen = tinyStore<{ table: string; defaults?: Record<string, unknown> } | null>(null);
