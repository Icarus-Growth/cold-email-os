/* The editor's text as plain blocks (one per paragraph, heading or list line), and the marks
 * the checks put over it.
 *
 * The checks (lib/readability.ts, lib/senders) work on plain text: block number + character
 * offset. Inside one ProseMirror text block each character is one position, and a line break
 * is one position too (it is given here as "\n"), so a mark's position is start + offset.
 *
 * The marks are decorations: they change nothing in the document, they are not saved, and
 * undo does not see them. A click on one shows why it is there (data-why). */
import { Plugin, PluginKey, type EditorState, type Transaction } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import type { Node as PMNode } from '@tiptap/pm/model';

export interface TextBlock { text: string; heading: boolean; start: number }

/** Every text block of the document, in order. */
export function blocksOf(doc: PMNode): TextBlock[] {
  const out: TextBlock[] = [];
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    let text = '';
    node.forEach((child) => { text += child.isText ? child.text || '' : '\n'; });
    out.push({ text, heading: node.type.name === 'heading', start: pos + 1 });
    return false;
  });
  return out;
}

/** One mark over the text: block + offsets, the colour class, and the reason. */
export interface Span { block: number; from: number; to: number; cls: string; why: string }

const key = new PluginKey<DecorationSet>('docMarks');

/** The plugin that draws the marks. Set them with setMarks(); edits move them until the next set. */
export function marksPlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key,
    state: {
      init: () => DecorationSet.empty,
      apply(tr: Transaction, set: DecorationSet) {
        const next = tr.getMeta(key) as DecorationSet | undefined;
        return next || set.map(tr.mapping, tr.doc);
      },
    },
    props: { decorations: (state: EditorState) => key.getState(state) },
  });
}

/** Put these marks over the text (replacing the last ones). */
export function setMarks(state: EditorState, dispatch: (tr: Transaction) => void, spans: Span[]): void {
  const blocks = blocksOf(state.doc);
  const size = state.doc.content.size;
  const decos: Decoration[] = [];
  spans.forEach((s) => {
    const b = blocks[s.block];
    if (!b || s.to <= s.from) return;
    const from = b.start + s.from, to = Math.min(b.start + s.to, size);
    if (from >= to) return;
    decos.push(Decoration.inline(from, to, { class: s.cls, 'data-why': s.why }));
  });
  dispatch(state.tr.setMeta(key, DecorationSet.create(state.doc, decos)).setMeta('addToHistory', false));
}

/** Text edits (block + offsets) as one transaction: one step to undo. Last edit first, so the
 *  earlier offsets still hold. */
export function editsTransaction(state: EditorState, edits: Array<{ block: number; from: number; to: number; text: string }>): Transaction | null {
  if (!edits.length) return null;
  const blocks = blocksOf(state.doc);
  const tr = state.tr;
  edits.slice().sort((p, q) => q.block - p.block || q.from - p.from).forEach((e) => {
    const b = blocks[e.block];
    if (!b) return;
    if (e.text) tr.insertText(e.text, b.start + e.from, b.start + e.to);
    else tr.delete(b.start + e.from, b.start + e.to);
  });
  return tr.docChanged ? tr : null;
}
