import React, { useEffect, useRef, useState } from 'react';
import { Bold, Italic, Link2, List, ListOrdered } from 'lucide-react';
import { cleanRich, richHtml } from '../lib/rich';

export interface RichTextProps {
  /** The stored value: cleaned HTML, or old plain text (shown with its line breaks). */
  value?: string | null;
  /** Called when focus leaves the editor (toolbar and link box included), only if the text changed.
   *  Gets the cleaned HTML, or null when the editor was emptied. */
  onSave: (html: string | null) => void;
  placeholder?: string;
  /** A stable name for the box, e.g. "tasks:<id>:notes" (tests find a box by it). */
  field?: string;
  'aria-label'?: string;
  /** Called as the person types: true when the box holds any text. */
  onTyping?: (hasText: boolean) => void;
}

/** Rich text editor for Notes / To do: bold, italics, bullets, numbered list, link.
 *
 *  It owns its own DOM: React never writes into the editable area after it
 *  mounts. A new `value` from the store is taken only while the editor does
 *  NOT have focus, so a save, a live update or a reload never moves the
 *  caret, drops focus or scrolls the box while someone is typing. */
export function RichText({ value, onSave, placeholder, field, onTyping, ...rest }: RichTextProps) {
  const ed = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const linkBox = useRef<HTMLInputElement>(null);
  const start = useRef<string>(cleanRich(richHtml(value)));
  const savedRange = useRef<Range | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);

  // First paint.
  useEffect(() => { if (ed.current) ed.current.innerHTML = richHtml(value); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A new value from outside: take it only when nobody is typing here.
  useEffect(() => {
    const el = ed.current, w = wrap.current;
    if (!el || !w) return;
    if (w.contains(document.activeElement)) return;
    const next = richHtml(value);
    if (cleanRich(next) === cleanRich(el.innerHTML)) return;
    el.innerHTML = next;
    start.current = cleanRich(next);
  }, [value]);

  function save() {
    const el = ed.current;
    if (!el) return;
    const html = cleanRich(el.innerHTML);
    if (html === start.current) return;
    start.current = html;
    onSave(html || null);
  }

  function cmd(name: string) {
    return (e: React.MouseEvent) => {
      // mousedown, not click: the editor keeps focus and its selection.
      e.preventDefault();
      document.execCommand(name, false);
    };
  }

  function openLink(e: React.MouseEvent) {
    e.preventDefault();
    const sel = window.getSelection();
    savedRange.current = sel && sel.rangeCount && ed.current && ed.current.contains(sel.anchorNode)
      ? sel.getRangeAt(0).cloneRange() : null;
    setLinkOpen(true);
    setTimeout(() => linkBox.current && linkBox.current.focus(), 0);
  }

  function applyLink() {
    const box = linkBox.current, el = ed.current;
    if (!box || !el) return;
    let url = box.value.trim();
    setLinkOpen(false);
    if (!url) { el.focus(); return; }
    if (!/^(https?:|mailto:)/i.test(url)) url = 'https://' + url;
    el.focus();
    const r = savedRange.current;
    if (r) { const sel = window.getSelection(); if (sel) { sel.removeAllRanges(); sel.addRange(r); } }
    if (r && !r.collapsed) document.execCommand('createLink', false, url);
    else document.execCommand('insertHTML', false, '<a href="' + url.replace(/"/g, '&quot;') + '">' + url.replace(/</g, '&lt;') + '</a>');
    box.value = '';
    // Carry on typing AFTER the link, not inside it (Enter + a list would
    // otherwise be built inside the <a>).
    const sel2 = window.getSelection();
    const end = sel2 && sel2.rangeCount ? sel2.getRangeAt(0).endContainer : null;
    const endEl = end ? (end.nodeType === 1 ? (end as Element) : end.parentElement) : null;
    const a = endEl ? endEl.closest('a') : null;
    if (sel2 && a && el.contains(a)) {
      const after = document.createRange(); after.setStartAfter(a); after.collapse(true);
      sel2.removeAllRanges(); sel2.addRange(after);
    }
    save();
  }

  const btn = 'inline-flex items-center justify-center w-[26px] h-[26px] rounded-[6px] text-muted hover:bg-chrome hover:text-ink';
  return (
    <div ref={wrap} className="rounded-[10px] border border-line bg-card focus-within:border-[var(--border-focus)] focus-within:ring-2 focus-within:ring-[var(--focus-ring)]"
      onClick={(e) => e.stopPropagation()}
      onBlur={(e) => {
        // Save when focus leaves the whole editor (toolbar and link box included).
        if (e.relatedTarget && wrap.current && wrap.current.contains(e.relatedTarget as Node)) return;
        setTimeout(() => {
          if (wrap.current && !wrap.current.contains(document.activeElement)) { setLinkOpen(false); save(); }
        }, 0);
      }}>
      <div className="flex items-center gap-0.5 px-1.5 pt-1 border-b border-line2 pb-1" role="toolbar" aria-label="Formatting">
        <button type="button" className={btn} aria-label="Bold" title="Bold" onMouseDown={cmd('bold')}><Bold size={14} /></button>
        <button type="button" className={btn} aria-label="Italic" title="Italic" onMouseDown={cmd('italic')}><Italic size={14} /></button>
        <button type="button" className={btn} aria-label="Bullet list" title="Bullet list" onMouseDown={cmd('insertUnorderedList')}><List size={14} /></button>
        <button type="button" className={btn} aria-label="Numbered list" title="Numbered list" onMouseDown={cmd('insertOrderedList')}><ListOrdered size={14} /></button>
        <button type="button" className={btn} aria-label="Link" title="Link" onMouseDown={openLink}><Link2 size={14} /></button>
      </div>
      {linkOpen && (
        <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-line2">
          <input ref={linkBox} type="url" placeholder="https://…" aria-label="Link address"
            className="flex-1 min-w-0 h-[28px] px-2 rounded-[6px] border border-line text-[12.5px] focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); applyLink(); }
              if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setLinkOpen(false); ed.current && ed.current.focus(); }
            }} />
          <button type="button" className="h-[28px] px-2 rounded-[6px] border border-line text-[12px] text-ink2" onClick={applyLink}>Add link</button>
        </div>
      )}
      <div ref={ed} contentEditable suppressContentEditableWarning role="textbox" aria-multiline="true"
        aria-label={rest['aria-label'] || placeholder} data-field={field} data-placeholder={placeholder || ''}
        className="os-rich-body min-h-[72px] max-h-[420px] overflow-y-auto px-3 py-2 text-[13px] text-ink focus:outline-none"
        onInput={onTyping ? (e) => onTyping(!!(e.currentTarget.textContent || '').trim()) : undefined}
        onClick={(e) => {
          // Links open with Cmd/Ctrl-click; a plain click edits.
          const a = (e.target as HTMLElement).closest && (e.target as HTMLElement).closest('a');
          if (a && (e.metaKey || e.ctrlKey)) window.open((a as HTMLAnchorElement).href, '_blank', 'noopener');
        }}
        onPaste={(e) => {
          const html = e.clipboardData && e.clipboardData.getData('text/html');
          const text = e.clipboardData && e.clipboardData.getData('text/plain');
          e.preventDefault();
          if (html) document.execCommand('insertHTML', false, cleanRich(html));
          else if (text) document.execCommand('insertText', false, text);
        }} />
    </div>
  );
}

/** Read-only rich text (a stored value shown as formatted text). */
export function RichView({ value, empty = '—' }: { value?: string | null; empty?: string }) {
  const html = richHtml(value);
  if (!html) return <div className="text-muted text-[13px]">{empty}</div>;
  return <div className="os-rich-body text-[13px] text-ink" dangerouslySetInnerHTML={{ __html: html }} />;
}
