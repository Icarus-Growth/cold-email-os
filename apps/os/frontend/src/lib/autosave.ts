/* Autosave for one document. It saves 1 second after typing stops, and at once on flush()
 * (the editor calls it on close). One save runs at a time; typing during a save is saved next.
 *
 * A save that the database refuses with document_conflict (someone else saved a newer version)
 * stops all saving: the text stays on screen, and the person reloads to see the other changes.
 * Any other failure says so and tries again on the next change or flush.
 *
 * No imports: tests/documents.test.mjs runs this file in Node as it is. */

export type SaveState = 'saved' | 'dirty' | 'saving' | 'conflict' | 'error';
export interface SaveStatus { state: SaveState; version: number; savedAt: number | null; error: string | null }

export interface SaverOptions {
  body: string;
  version: number;
  /** Save this text over this version; resolves with the new version. */
  save: (body: string, version: number) => Promise<{ version: number }>;
  onStatus?: (s: SaveStatus) => void;
  delay?: number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (t: unknown) => void;
}

/** True for the database's "someone else saved first" refusal. */
export const isConflict = (err: unknown) => /document_conflict/.test(String((err as Error)?.message || err));

export class DocSaver {
  private body: string;
  private savedBody: string;
  private timer: unknown = null;
  private running: Promise<void> | null = null;
  private o: SaverOptions;
  status: SaveStatus;
  constructor(o: SaverOptions) {
    this.o = o;
    this.body = o.body;
    this.savedBody = o.body;
    this.status = { state: 'saved', version: o.version, savedAt: null, error: null };
  }

  private set(s: Partial<SaveStatus>) {
    this.status = { ...this.status, ...s };
    if (this.o.onStatus) this.o.onStatus(this.status);
  }

  /** The text changed. */
  edit(body: string): void {
    this.body = body;
    if (this.status.state === 'conflict') return;
    if (body === this.savedBody && this.status.state !== 'saving') { this.cancel(); this.set({ state: 'saved' }); return; }
    if (this.status.state !== 'saving') this.set({ state: 'dirty', error: null });
    this.cancel();
    const set = this.o.setTimer || ((fn: () => void, ms: number) => setTimeout(fn, ms));
    this.timer = set(() => { this.timer = null; void this.run(); }, this.o.delay ?? 1000);
  }

  private cancel() {
    if (this.timer !== null) { (this.o.clearTimer || ((t: unknown) => clearTimeout(t as ReturnType<typeof setTimeout>)))(this.timer); this.timer = null; }
  }

  /** Save now if anything is unsaved (on close). Resolves when nothing is left to save. */
  async flush(): Promise<void> {
    this.cancel();
    if (this.running) await this.running;
    if (this.status.state !== 'conflict' && this.body !== this.savedBody) await this.run();
  }

  private run(): Promise<void> {
    if (this.running) return this.running;
    if (this.status.state === 'conflict' || this.body === this.savedBody) return Promise.resolve();
    const body = this.body;
    this.set({ state: 'saving' });
    this.running = this.o.save(body, this.status.version).then((r) => {
      this.savedBody = body;
      this.running = null;
      this.set({ version: r.version, savedAt: Date.now(), state: this.body === body ? 'saved' : 'dirty' });
      /* Typed during the save: the timer saves it, or now if the timer already fired. */
      if (this.body !== body && this.timer === null) return this.run();
    }, (err) => {
      this.running = null;
      if (isConflict(err)) this.set({ state: 'conflict', error: null });
      else this.set({ state: 'error', error: String((err as Error)?.message || err) });
    });
    return this.running;
  }
}
