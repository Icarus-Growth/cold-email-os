/* The copy editor: one document, in a large panel over its card (or over the client page),
 * at its own address (?doc=<field>). Contract 0013.
 *
 * Markdown in and out (tiptap-markdown); the database keeps the Markdown. It saves 1 second
 * after typing stops and on close (lib/autosave.ts). When someone else saved first, saving
 * stops and the text stays on screen until the person reloads. History lists the last 20 saves.
 *
 * The readability panel on the right (on/off at the top right, remembered in this browser)
 * marks the text as you type: lib/readability.ts, the agency type's line (lib/doccheck.ts)
 * and for cold email the sending-tool checks (lib/senders). */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { EditorContent, Extension, useEditor, useEditorState, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Placeholder } from '@tiptap/extensions';
import { Markdown } from 'tiptap-markdown';
import { Bold, ChevronRight, Copy, Heading2, History as HistoryIcon, Italic, Link2, List, ListOrdered, Quote, Redo2, RotateCcw, Undo2, X } from 'lucide-react';
import type { FieldDef } from '../../config';
import { Button, IconButton, Modal, Notice, useEscapeLayer } from '../../ui';
import { saveError, useData, type Data, type Row } from '../../lib/store';
import { AGENCY, recordDef } from '../../lib/schema';
import { closeDoc, type Route } from '../../lib/router';
import { confirm, toast } from '../../lib/ui';
import { dateTime } from '../../lib/format';
import { isMissingTable } from '../../lib/db';
import { openDocument, refreshDocs, saveDocument, versions, type DocKey } from '../../lib/documents';
import { DocSaver, type SaveStatus } from '../../lib/autosave';
import { analyze, countWords, type Readability } from '../../lib/readability';
import { checkCopy, toolOf, type CopyCheck, type Tool } from '../../lib/senders';
import { adScript, caption, emailCopy, type Line } from '../../lib/doccheck';
import { copyText } from '../records/CardPanel';
import { blocksOf, editsTransaction, marksPlugin, setMarks, type Span, type TextBlock } from './marks';
import { Checks, type HideKind } from './Checks';
import { ago, docPlace } from './DocField';
import { READ_ONLY, canChangeDoc, dbMessage, isDenied } from '../../lib/docaccess';

/* ---------- remembered in this browser ------------------------------------- */

const PANEL_KEY = 'os-doc-panel';
const HIDE_KEY = 'os-doc-hide';
function readPanel(): boolean {
  try { return localStorage.getItem(PANEL_KEY) !== '0'; } catch { return true; }
}
function readHidden(): Record<string, boolean> {
  try { const v = JSON.parse(localStorage.getItem(HIDE_KEY) || 'null'); return v && typeof v === 'object' ? v : {}; } catch { return {}; }
}
function keep(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private window: not kept */ }
}

/* ---------- which document ------------------------------------------------- */

interface Place { key: DocKey | null; f: FieldDef | null; row: Row | null; table: string; title: string; crumb: string }

/** The field, its row and the document key for the route (null parts when they are not there). */
function placeOf(S: Data, r: Route): Place {
  const field = r.doc || '';
  if (r.card) {
    const def = recordDef(r.card.table);
    const row = def ? S.row(r.card.table, r.card.id) : null;
    const f = def ? def.sections.flatMap((s) => s.fields).find((x) => x.key === field && x.type === 'document') || null : null;
    const at = row ? docPlace(r.card.table, row) : null;
    return { f, row, table: r.card.table, key: at && at.client && f ? { client: at.client, board: at.board, card: at.card, field } : null,
      title: f ? f.label : 'Document', crumb: row && def ? String(row[def.nameKey] || 'Untitled ' + def.item) : 'Card' };
  }
  const row = r.id ? S.clientById[r.id] || null : null;
  const f = AGENCY.clientSections.flatMap((s) => s.fields).find((x) => x.key === field && x.type === 'document') || null;
  return { f, row, table: 'clients', key: row && f ? { client: row.id, board: null, card: null, field } : null,
    title: f ? f.label : 'Document', crumb: row ? row.client_name || 'Unnamed client' : 'Client' };
}

/* ---------- the frame -------------------------------------------------------- */

function Frame({ crumb, title, status, actions, onClose, children }: {
  crumb: string; title: string; status?: React.ReactNode; actions?: React.ReactNode; onClose: () => void; children: React.ReactNode;
}) {
  useEscapeLayer('modal', onClose);
  return (
    <>
      <div className="fixed inset-0 z-[45] bg-[var(--overlay-light)]" aria-hidden onMouseDown={onClose} />
      <section role="dialog" aria-modal="true" aria-label={title} data-doc-editor
        className="fixed z-[46] top-2 bottom-2 right-2 left-2 min-[901px]:left-[248px] max-[720px]:inset-0 max-[720px]:rounded-none rounded-[14px] bg-card border border-line shadow-[var(--shadow-xl)] flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-5 max-[720px]:px-3 h-[56px] border-b border-line2 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 text-[11.5px] text-muted min-w-0">
              <span className="truncate">{crumb}</span><ChevronRight size={11} className="shrink-0" />
            </div>
            <h2 className="font-display text-[16px] leading-[22px] font-semibold text-ink truncate">{title}</h2>
          </div>
          {status}
          {actions}
          <IconButton icon={X} label="Close the editor" onClick={onClose} />
        </div>
        {children}
      </section>
    </>
  );
}

/** The Readability on/off switch (top right). */
function PanelSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label="Readability" onClick={() => onChange(!on)} data-panel-switch
      className="inline-flex items-center gap-2 h-[30px] px-2.5 rounded-[9px] text-[12.5px] text-ink2 hover:bg-ground">
      <span className={`relative w-[30px] h-[17px] rounded-full transition-colors ${on ? 'bg-[var(--button-primary-bg)]' : 'bg-[var(--border-primary_hover)]'}`}>
        <span className={`absolute top-[2px] w-[13px] h-[13px] rounded-full bg-white transition-[left] ${on ? 'left-[15px]' : 'left-[2px]'}`} />
      </span>
      <span className="max-[720px]:hidden">Readability</span>
    </button>
  );
}

/* ---------- open, then edit ---------------------------------------------------- */

export function DocEditor({ r }: { r: Route }) {
  const S = useData();
  const p = placeOf(S, r);
  const [doc, setDoc] = useState<Row | null>(null);
  const [fail, setFail] = useState<{ text: string; missing: boolean } | null>(null);
  const [load, setLoad] = useState(0);
  const k = p.key;
  const id = k ? [k.client, k.board, k.card, k.field].join(':') : '';

  useEffect(() => {
    if (!k) return;
    let live = true;
    setDoc(null); setFail(null);
    openDocument(k).then((d) => { if (live) setDoc(d); },
      (err) => { if (live) setFail({ text: saveError(err), missing: isMissingTable(err) }); });
    return () => { live = false; };
  }, [id, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const leave = () => { closeDoc(); if (k) refreshDocs(k.client, k.board, k.card); };
  if (!k || doc === null) {
    const why = !p.row ? 'This card or client is not here. It may have been deleted, or the link is wrong.'
      : !p.f ? 'This ' + (r.card ? 'card' : 'client page') + ' has no document called "' + (r.doc || '') + '".'
      : !k ? 'Pick a client for this card first: a document belongs to a client.'
      : fail ? (fail.missing ? 'Documents need database change 0013. Ask whoever runs the database to apply it.' : fail.text)
      : null;
    return (
      <Frame crumb={p.crumb} title={p.title} onClose={leave}>
        <div className="p-6">{why ? <Notice title="This document cannot open." tone="bad">{why}</Notice> : <Notice title="Opening the document…" />}</div>
      </Frame>
    );
  }
  return <DocBody key={doc.id + ':' + load} doc={doc} place={p} onReload={() => setLoad((n) => n + 1)} onLeave={leave} />;
}

/* ---------- the editor ----------------------------------------------------------- */

const markdownOf = (e: Editor): string => (e.storage as unknown as { markdown: { getMarkdown(): string } }).markdown.getMarkdown();
const wordsOf = (blocks: TextBlock[]) => blocks.reduce((n, b) => n + countWords(b.text), 0);

/** The checks for the text on screen. */
function runChecks(blocks: TextBlock[], check: FieldDef['check'], row: Row | null, tool: Tool): { r: Readability; cold: CopyCheck | null; extra: { title: string; lines: Line[] } | null } {
  const texts = blocks.map((b) => b.text);
  const r = analyze(texts);
  const cold = check === 'cold-email' ? checkCopy(blocks.map((b) => ({ text: b.text, heading: b.heading })), tool) : null;
  const extra = check === 'ad-script' ? { title: 'Ad length', lines: adScript(r.words) }
    : check === 'caption' ? { title: 'Caption length', lines: caption(texts.join('\n'), row ? row.platform : '') }
    : check === 'email-copy' ? { title: 'Subject and preview text', lines: emailCopy(texts) }
    : null;
  return { r, cold, extra };
}

function DocBody({ doc, place, onReload, onLeave }: { doc: Row; place: Place; onReload: () => void; onLeave: () => void }) {
  const [status, setStatus] = useState<SaveStatus>({ state: 'saved', version: doc.version, savedAt: null, error: null });
  const [panel, setPanel] = useState(readPanel);
  const [hidden, setHidden] = useState(readHidden);
  const [tool, setTool] = useState<Tool>(place.table === 'clients' ? 'Other' : toolOf(place.row && place.row.sending_tool));
  const [blocks, setBlocks] = useState<TextBlock[]>([]);
  const [pop, setPop] = useState<{ whys: string[]; top: number; left: number } | null>(null);
  const [history, setHistory] = useState(false);
  const saver = useRef<DocSaver | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const scroller = useRef<HTMLDivElement>(null);
  /* A client-page document is for Owners and Admins; others read it (0015). A refusal from the
   * database (their access changed) makes it read-only too, with the database's own sentence. */
  const S = useData();
  const allowed = canChangeDoc(S.me && S.me.access, place.table === 'clients' ? null : place.table);
  const [denied, setDenied] = useState<string | null>(null);
  const canEdit = allowed && !denied;
  /* Escape in the text closes the editor (saving first); a "why" box open closes first. */
  const onEscape = useRef<() => void>(() => {});

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ underline: false, link: { openOnClick: false, autolink: true } }),
      Placeholder.configure({ placeholder: 'Write the copy here. Pasting from a Google Doc keeps headings, bold and lists.' }),
      Markdown.configure({ html: false, breaks: true, linkify: true, transformPastedText: true, transformCopiedText: true }),
      Extension.create({ name: 'docMarks', addProseMirrorPlugins: () => [marksPlugin()] }),
    ],
    content: String(doc.body_md || ''),
    editable: allowed,
    editorProps: {
      attributes: { class: 'os-doc', 'aria-label': place.title, spellcheck: 'true' },
      handleKeyDown: (_view, e) => { if (e.key !== 'Escape' || e.isComposing) return false; onEscape.current(); return true; },
    },
    onCreate: ({ editor: e }) => {
      setBlocks(blocksOf(e.state.doc));
      if (!allowed) return;   // read-only: nothing is ever saved
      saver.current = new DocSaver({
        body: markdownOf(e), version: doc.version, onStatus: setStatus,
        save: (body, version) => saveDocument(doc.id, version, body, wordsOf(blocksOf(e.state.doc))),
      });
    },
    onUpdate: ({ editor: e }) => {
      setPop(null);
      if (saver.current) saver.current.edit(markdownOf(e));
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setBlocks(blocksOf(e.state.doc)), 250);
    },
  });
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (status.state === 'error' && isDenied(status.error)) setDenied(dbMessage(status.error) || READ_ONLY);
  }, [status]);
  useEffect(() => { if (editor && !editor.isDestroyed) editor.setEditable(canEdit); }, [editor, canEdit]);

  const check = place.f ? place.f.check : undefined;
  const result = useMemo(() => runChecks(blocks, check, place.row, tool), [blocks, check, place.row, tool]);

  /* The marks over the text: the readability kinds not hidden, and the cold email flags. */
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const spans: Span[] = [];
    if (panel) {
      result.r.marks.forEach((m) => { if (!hidden[m.kind]) spans.push({ block: m.block, from: m.from, to: m.to, cls: 'doc-mark-' + m.kind, why: m.why }); });
      if (result.cold && !hidden.flags) result.cold.flags.forEach((f) => spans.push({ block: f.block, from: f.from, to: f.to, cls: 'doc-flag', why: f.why }));
    }
    setMarks(editor.state, editor.view.dispatch, spans);
  }, [editor, result, panel, hidden]);

  /* Leaving the page with unsaved text: the browser asks first. */
  const unsaved = status.state === 'dirty' || status.state === 'saving' || status.state === 'error' || status.state === 'conflict';
  useEffect(() => {
    if (!unsaved) return;
    const stop = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', stop);
    return () => window.removeEventListener('beforeunload', stop);
  }, [unsaved]);

  const close = async () => {
    const s = saver.current;
    if (s) await s.flush();
    const st = s ? s.status.state : 'saved';
    if (st === 'conflict' || st === 'error') {
      confirm({ title: 'Close without saving?', verb: 'Close',
        body: st === 'conflict' ? 'Someone else changed this document. Your changes since the last save are not saved. Copy your text first if you need it.'
          : 'The last changes did not save. If you close now, they are lost.',
        run: onLeave });
      return;
    }
    onLeave();
  };

  onEscape.current = () => { if (pop) setPop(null); else void close(); };

  const togglePanel = (on: boolean) => { setPanel(on); keep(PANEL_KEY, on ? '1' : '0'); setPop(null); };
  const hide = (kind: HideKind) => setHidden((h) => { const next = { ...h, [kind]: !h[kind] }; keep(HIDE_KEY, JSON.stringify(next)); return next; });

  /* Fix all: worked out again on the text as it is now, applied as one step (one undo). */
  const fixAll = () => {
    if (!editor) return;
    const now = blocksOf(editor.state.doc);
    const c = checkCopy(now.map((b) => ({ text: b.text, heading: b.heading })), tool);
    const tr = editsTransaction(editor.state, c.fixes);
    if (!tr) return;
    editor.view.dispatch(tr);
    editor.commands.focus();   // so Ctrl/Cmd+Z undoes it at once
    setBlocks(blocksOf(editor.state.doc));
    toast('Fixed ' + c.fixes.length + (c.fixes.length === 1 ? ' place' : ' places') + '. Undo puts them back.', 'good');
  };
  const goTo = (i: number) => {
    const f = result.cold && result.cold.flags[i];
    if (!editor || !f) return;
    const b = blocksOf(editor.state.doc)[f.block];
    if (b) editor.chain().focus().setTextSelection({ from: b.start + f.from, to: b.start + f.to }).scrollIntoView().run();
  };

  /* A click on a mark: why it is there (every mark under the pointer, inner first). */
  const onClick = (e: React.MouseEvent) => {
    const box = scroller.current;
    let el = (e.target as HTMLElement).closest('[data-why]') as HTMLElement | null;
    if (!el || !box) { setPop(null); return; }
    const whys: string[] = [];
    const first = el;
    while (el && box.contains(el)) { const w = el.getAttribute('data-why'); if (w && whys.indexOf(w) < 0) whys.push(w); el = el.parentElement ? el.parentElement.closest('[data-why]') as HTMLElement | null : null; }
    const a = first.getBoundingClientRect(), c = box.getBoundingClientRect();
    setPop({ whys, top: a.bottom - c.top + box.scrollTop + 6, left: Math.max(8, Math.min(a.left - c.left, c.width - 300)) });
  };

  const restore = (v: Row) => confirm({
    title: 'Restore this version?', verb: 'Restore',
    body: 'The editor gets the text saved ' + dateTime(v.saved_at) + '. The text now in the editor stays in the history.',
    run: () => {
      if (!editor) return;
      editor.commands.setContent(String(v.body_md || ''));
      if (saver.current) saver.current.edit(markdownOf(editor));
      setBlocks(blocksOf(editor.state.doc));
      setHistory(false);
    },
  });

  const statusLine = !canEdit ? 'Read only'
    : status.state === 'saving' ? 'Saving…'
    : status.state === 'dirty' ? 'Not saved yet'
    : status.state === 'error' ? 'Not saved'
    : status.state === 'conflict' ? 'Not saved'
    : status.savedAt ? 'Saved' : doc.version > 1 ? 'Saved ' + ago(doc.updated_at) : 'Saved';

  return (
    <Frame crumb={place.crumb} title={place.title} onClose={close}
      status={<span className={`text-[12px] whitespace-nowrap max-[720px]:text-[11px] ${status.state === 'error' || status.state === 'conflict' ? 'text-bad' : 'text-muted'}`} data-save-state={status.state} aria-live="polite">{statusLine}</span>}
      actions={<>
        <Button size="sm" variant="ghost" icon={HistoryIcon} aria-label="History" title="History" onClick={() => setHistory(true)}><span className="max-[720px]:hidden">History</span></Button>
        <PanelSwitch on={panel} onChange={togglePanel} />
      </>}>
      {status.state === 'conflict' && (
        <div role="alert" className="flex items-center gap-2 flex-wrap px-5 py-2.5 bg-[var(--tint-bad)] text-[13px] text-bad border-b border-line2" data-conflict>
          <span className="flex-1 min-w-[200px]">Someone else changed this. Reload to see their changes.</span>
          <Button size="sm" icon={Copy} onClick={() => editor && copyText(markdownOf(editor), 'Your text is copied.')}>Copy my text</Button>
          <Button size="sm" variant="primary" icon={RotateCcw} onClick={onReload}>Reload</Button>
        </div>
      )}
      {!canEdit && (
        <div role="status" className="px-5 py-2.5 bg-ground text-[13px] text-ink2 border-b border-line2" data-read-only>
          {denied || READ_ONLY}
        </div>
      )}
      {canEdit && status.state === 'error' && (
        <div role="alert" className="px-5 py-2.5 bg-[var(--tint-warn)] text-[13px] text-ink2 border-b border-line2">
          Not saved: {dbMessage(status.error) || saveError(status.error)} It tries again when you type, and when you close.
        </div>
      )}
      {canEdit && <Toolbar editor={editor} />}
      <div className="flex-1 min-h-0 flex max-[900px]:flex-col">
        <div ref={scroller} className="relative flex-1 min-w-0 min-h-0 overflow-y-auto" data-scroll onClick={onClick}>
          <div className="max-w-[720px] mx-auto px-8 py-6 max-[720px]:px-4"><EditorContent editor={editor} /></div>
          {pop && (
            <div role="tooltip" className="absolute z-10 w-[290px] rounded-[10px] border border-line bg-card shadow-[var(--shadow-lg)] px-3 py-2 text-[12.5px] text-ink2 space-y-1" style={{ top: pop.top, left: pop.left }} data-why-pop>
              {pop.whys.map((w, i) => <p key={i}>{w}</p>)}
            </div>
          )}
        </div>
        {panel && (
          <aside aria-label="Readability" className="w-[300px] shrink-0 border-l border-line2 overflow-y-auto px-4 py-4 max-[900px]:w-full max-[900px]:border-l-0 max-[900px]:border-t max-[900px]:max-h-[42%]" data-scroll>
            <Checks r={result.r} hidden={hidden} onHide={hide} extra={result.extra}
              cold={result.cold ? { check: result.cold, tool, onTool: setTool, onFixAll: fixAll, onGo: goTo, canEdit } : null} />
          </aside>
        )}
      </div>
      {history && <History docId={doc.id} onClose={() => setHistory(false)} onRestore={canEdit ? restore : null} />}
    </Frame>
  );
}

/* ---------- toolbar ----------------------------------------------------------------- */

function Toolbar({ editor }: { editor: Editor | null }) {
  const on = useEditorState({
    editor,
    selector: ({ editor: e }) => e ? {
      bold: e.isActive('bold'), italic: e.isActive('italic'), h2: e.isActive('heading', { level: 2 }), bullet: e.isActive('bulletList'),
      ordered: e.isActive('orderedList'), quote: e.isActive('blockquote'), link: e.isActive('link'), undo: e.can().undo(), redo: e.can().redo(),
    } : null,
  });
  const [link, setLink] = useState<string | null>(null);
  if (!editor || !on) return null;
  const btn = (label: string, Icon: typeof Bold, active: boolean, run: () => void, disabled = false) => (
    <button type="button" aria-label={label} title={label} aria-pressed={active} disabled={disabled} onMouseDown={(e) => e.preventDefault()} onClick={run}
      className={`w-[30px] h-[30px] inline-flex items-center justify-center rounded-[8px] ${active ? 'bg-ground text-ink' : 'text-muted hover:bg-ground hover:text-ink'} disabled:opacity-40 disabled:hover:bg-transparent`}>
      <Icon size={15} />
    </button>
  );
  const apply = () => {
    const url = (link || '').trim();
    if (url) editor.chain().focus().extendMarkRange('link').setLink({ href: /^[a-z]+:/i.test(url) ? url : 'https://' + url }).run();
    else editor.chain().focus().extendMarkRange('link').unsetLink().run();
    setLink(null);
  };
  return (
    <div className="flex items-center gap-0.5 px-4 max-[720px]:px-2 h-[42px] border-b border-line2 shrink-0 overflow-x-auto" role="toolbar" aria-label="Format">
      {btn('Bold', Bold, on.bold, () => editor.chain().focus().toggleBold().run())}
      {btn('Italic', Italic, on.italic, () => editor.chain().focus().toggleItalic().run())}
      {btn('Heading', Heading2, on.h2, () => editor.chain().focus().toggleHeading({ level: 2 }).run())}
      {btn('Bulleted list', List, on.bullet, () => editor.chain().focus().toggleBulletList().run())}
      {btn('Numbered list', ListOrdered, on.ordered, () => editor.chain().focus().toggleOrderedList().run())}
      {btn('Quote', Quote, on.quote, () => editor.chain().focus().toggleBlockquote().run())}
      {btn('Link', Link2, on.link, () => setLink(link === null ? String(editor.getAttributes('link').href || '') : null))}
      {link !== null && (
        <input autoFocus value={link} placeholder="Paste a link, Enter to add (empty removes it)" aria-label="Link address"
          onChange={(e) => setLink(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); apply(); } if (e.key === 'Escape') { e.preventDefault(); setLink(null); } }}
          className="ml-1 h-[28px] w-[260px] max-w-[50vw] rounded-[8px] border border-line px-2 text-[12.5px] focus:outline-none focus:border-[var(--border-focus)]" />
      )}
      <span className="w-px h-5 bg-[var(--border-primary)] mx-1.5" aria-hidden />
      {btn('Undo', Undo2, false, () => editor.chain().focus().undo().run(), !on.undo)}
      {btn('Redo', Redo2, false, () => editor.chain().focus().redo().run(), !on.redo)}
    </div>
  );
}

/* ---------- history ------------------------------------------------------------------ */

function History({ docId, onClose, onRestore }: { docId: string; onClose: () => void; onRestore: ((v: Row) => void) | null }) {
  const S = useData();
  const [list, setList] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { versions(docId).then(setList, (e) => setErr(saveError(e))); }, [docId]);
  return (
    <Modal title="History" wide onClose={onClose}>
      <p className="text-[12.5px] text-muted mb-3">The text before each of the last 20 saves, newest first.{onRestore ? ' Restore puts a version back in the editor; it saves like any change.' : ''}</p>
      {err ? <Notice title="The history did not load." tone="bad">{err}</Notice>
        : !list ? <Notice title="Loading the history…" />
        : !list.length ? <Notice title="No saves yet.">Each save keeps the text it replaced here.</Notice>
        : (
          <ul className="divide-y divide-[var(--border-secondary)]" data-history>
            {list.map((v, i) => (
              <li key={v.version + ':' + i} className="py-2.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="flex-1 min-w-0 text-[13px] text-ink">
                    {dateTime(v.saved_at)} <span className="text-muted">· {S.teamName(v.saved_by) || 'someone'} · {(v.word_count || 0).toLocaleString()} words</span>
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setOpen(open === i ? null : i)}>{open === i ? 'Hide' : 'Show'}</Button>
                  {onRestore && <Button size="sm" onClick={() => onRestore(v)}>Restore</Button>}
                </div>
                {open === i && <pre className="mt-2 max-h-[240px] overflow-y-auto whitespace-pre-wrap rounded-[10px] bg-ground px-3 py-2 text-[12.5px] text-ink2 font-sans">{String(v.body_md || '') || '(empty)'}</pre>}
              </li>
            ))}
          </ul>
        )}
    </Modal>
  );
}
