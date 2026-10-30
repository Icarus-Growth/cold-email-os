/* Rich text (notes, feedback, briefs).
 *
 * Stored as a small, cleaned piece of HTML: paragraphs, line breaks, bold,
 * italics, bullet and numbered lists, links (http/https/mailto only).
 * Anything else is dropped on the way in and on the way out, so a pasted web
 * page or a script tag never reaches the database or the screen. Older
 * plain-text values show as typed, line breaks kept.
 */

const RICH_TAGS: Record<string, string> = {
  P: 'p', DIV: 'p', BR: 'br', STRONG: 'strong', B: 'strong', EM: 'em', I: 'em',
  UL: 'ul', OL: 'ol', LI: 'li', A: 'a',
};

const RICH_INLINE: Record<string, 1> = { STRONG: 1, EM: 1, A: 1 };
const RICH_BLOCK: Record<string, 1> = { p: 1, ul: 1, ol: 1, li: 1 };

/** Clean any HTML down to the allowed tags. '' when nothing is left.
 * A block inside bold/italics/a link (a list typed right after a link at a
 * line end), or a list inside a paragraph, is lifted out, so a list is never
 * saved inside an <a>. Bold, italics and links never hold the spaces at their
 * edges, and empty ones are dropped, as are empty paragraphs. */
export function cleanRich(html?: string | null): string {
  const src = document.createElement('template');
  src.innerHTML = html || '';
  const out = document.createElement('div');
  (function walk(from: Node, to: Element, host: Element) {
    Array.prototype.forEach.call(from.childNodes, (n: Node) => {
      if (n.nodeType === 3) { to.appendChild(document.createTextNode(n.nodeValue || '')); return; }
      if (n.nodeType !== 1) return;
      const el = n as Element;
      const tag = RICH_TAGS[el.tagName];
      if (!tag) { if (!/^(SCRIPT|STYLE|IFRAME|OBJECT|TEMPLATE)$/.test(el.tagName)) walk(el, to, host); return; }
      if (RICH_BLOCK[tag] && (RICH_INLINE[to.tagName] || (to.tagName === 'P' && tag !== 'li'))) to = host;
      const e = document.createElement(tag);
      if (tag === 'a') {
        const href = (el.getAttribute('href') || '').trim();
        if (!/^(https?:|mailto:)/i.test(href)) { walk(el, to, host); return; }
        e.setAttribute('href', href); e.setAttribute('target', '_blank'); e.setAttribute('rel', 'noopener');
      }
      to.appendChild(e);
      if (tag !== 'br') walk(el, e, tag === 'p' ? to : RICH_BLOCK[tag] ? e : host);
    });
  })(src.content, out, out);
  Array.prototype.slice.call(out.querySelectorAll('strong, em, a')).reverse().forEach((el: Element) => {
    const parent = el.parentNode;
    if (!parent) return;
    const first = el.firstChild;
    let m: RegExpExecArray | null;
    if (first && first.nodeType === 3 && (m = /^\s+/.exec(first.nodeValue || ''))) {
      first.nodeValue = (first.nodeValue || '').slice(m[0].length);
      parent.insertBefore(document.createTextNode(m[0]), el);
    }
    const last = el.lastChild;
    if (last && last.nodeType === 3 && (m = /\s+$/.exec(last.nodeValue || ''))) {
      const v = last.nodeValue || '';
      last.nodeValue = v.slice(0, v.length - m[0].length);
      parent.insertBefore(document.createTextNode(m[0]), el.nextSibling);
    }
    if (!el.textContent && !el.querySelector('br')) parent.removeChild(el);
  });
  // An empty paragraph (no text, no line break) is what the editor leaves before a list it
  // lifted out of a line: drop it, or every list saves with a blank line above it.
  Array.prototype.slice.call(out.querySelectorAll('p')).forEach((el: Element) => {
    if (!(el.textContent || '').trim() && !el.querySelector('br, li') && el.parentNode) el.parentNode.removeChild(el);
  });
  const html2 = out.innerHTML;
  // An editor left with nothing but empty lines holds nothing.
  return (out.textContent || '').trim() || out.querySelector('li') ? html2 : '';
}

/** A stored value as safe HTML to show: old plain text keeps its line breaks. */
export function richHtml(value?: string | null): string {
  if (!value) return '';
  if (!/<[a-z][\s\S]*>/i.test(value)) {
    const d = document.createElement('div');
    d.textContent = value;
    return d.innerHTML.replace(/\n/g, '<br>');
  }
  return cleanRich(value);
}

/** A stored value as plain text (cards, table cells). */
export function richText(value?: string | null): string {
  const d = document.createElement('div');
  d.innerHTML = richHtml(value);
  return (d.textContent || '').trim();
}
