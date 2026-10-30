/* Tests for the copy editor's own code (contract 0013): the readability counts and marks
 * (src/lib/readability.ts), every sending-tool rule and Fix all (src/lib/senders), autosave
 * and a conflict (src/lib/autosave.ts), the per-type lines (src/lib/doccheck.ts), and Fix all
 * in the editor as one undo step (src/areas/docs/marks.ts). Node runs the .ts files as they are
 * (Node 22.18 or newer). Run: npm test */
import assert from 'node:assert/strict';

if (!process.features.typescript) {
  console.log('Document tests skipped: they need Node 22.18 or newer (this is ' + process.version + ').');
  process.exit(0);
}
const R = await import('../src/lib/readability.ts');
const S = await import('../src/lib/senders/index.ts');
const A = await import('../src/lib/autosave.ts');
const D = await import('../src/lib/doccheck.ts');
const M = await import('../src/areas/docs/marks.ts');
const P = await import('../src/lib/docaccess.ts');
const { Schema } = await import('@tiptap/pm/model');
const { EditorState } = await import('@tiptap/pm/state');
const { history, undo } = await import('@tiptap/pm/history');

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

/* ---------- readability ---------------------------------------------------------- */

test('ARI grade: 4.71 x letters/words + 0.5 x words/sentences - 21.43, rounded, never below 0', () => {
  assert.equal(R.ariGrade(17, 6, 1), 0);      // -5.1
  assert.equal(R.ariGrade(64, 5, 1), 41);     // 41.36
  assert.equal(R.ariGrade(77, 14, 1), 11);    // 11.48
  assert.equal(R.ariGrade(0, 0, 0), 0);
});

test('counts on a short plain sentence', () => {
  const r = R.analyze(['The cat sat on the mat.']);
  assert.deepEqual([r.grade, r.words, r.letters, r.characters, r.sentences, r.paragraphs], [0, 6, 17, 23, 1, 1]);
  assert.equal(r.marks.length, 0);
});

test('counts on long words', () => {
  const r = R.analyze(['Comprehensive documentation facilitates organizational understanding.']);
  assert.deepEqual([r.grade, r.words, r.letters, r.characters, r.sentences], [41, 5, 64, 69, 1]);
});

test('paragraphs and sentences: empty blocks do not count; ! and ? end a sentence', () => {
  const r = R.analyze(['One two three.', '', 'Four five. Six!']);
  assert.deepEqual([r.paragraphs, r.sentences, r.words], [2, 3, 6]);
});

test('a sentence of 14 words at grade 10 to 13 is hard (yellow); grade 14 or more is very hard (red)', () => {
  const hard = 'Teams build plans every month using clear simple charts before anyone starts making budget.';
  const r = R.analyze([hard]);
  assert.equal(r.grade, 11);
  assert.deepEqual(r.marks.map((m) => [m.kind, m.from, m.to]), [['hard', 0, hard.length]]);
  const very = 'Simple charts before anyone starts making budget simple charts before anyone starts making budget.';
  const v = R.analyze([very]);
  assert.equal(v.grade, 14);
  assert.deepEqual(v.marks.map((m) => m.kind), ['veryHard']);
  assert.equal(v.count.veryHard, 1);
  /* 13 words is never marked, whatever the grade. */
  assert.equal(R.analyze(['Simple charts before anyone starts making budget simple charts before anyone starts making.']).marks.length, 0);
});

test('passive voice and adverbs are blue; a simpler word is purple; each says why', () => {
  const r = R.analyze(['It was sent quickly.']);
  assert.deepEqual(r.marks.map((m) => [m.kind, m.from, m.to]), [['weak', 3, 11], ['weak', 12, 19]]);
  assert.match(r.marks[0].why, /Passive voice/);
  assert.match(r.marks[1].why, /Adverb/);
  const s = R.analyze(['We utilize it.']);
  assert.deepEqual(s.marks.map((m) => [m.kind, m.from, m.to]), [['simpler', 3, 10]]);
  assert.match(s.marks[0].why, /"use"/);
});

test('word count: a merge field or a spintax block is one word; parts with no letter or digit are not words', () => {
  assert.equal(R.countWords('Hi {{firstName | there}}, {Hey|Hello} team'), 4);
  assert.equal(R.countWords('— - 123 ok'), 2);
  assert.equal(R.countWords(''), 0);
});

test('reading time at 238 words a minute', () => {
  const r = R.analyze([Array(238).fill('word').join(' ') + '.']);
  assert.equal(r.readingSeconds, 60);
  assert.equal(R.duration(75), '1 min 15 s');
  assert.equal(R.duration(20), '20 s');
});

test('the grade label: "Too short to grade" under 20 words, else "Reading grade N" (never "Grade 0")', () => {
  assert.equal(R.gradeLabel(R.analyze([''])), 'Too short to grade');
  assert.equal(R.gradeLabel(R.analyze(['The cat sat on the mat.'])), 'Too short to grade');
  const long = R.analyze(['Teams build plans every month using clear simple charts before anyone starts making budget.', 'Then they check the plan with the client and send it.']);
  assert.ok(long.words >= R.MIN_GRADE_WORDS);
  assert.equal(R.gradeLabel(long), 'Reading grade ' + long.grade);
  assert.equal(R.gradeLabel({ words: 40, grade: 0 }), 'Reading grade 0');
});

/* ---------- sending tools --------------------------------------------------------- */

/** The flags of one line ("kind*" when Fix all corrects it) and the line after Fix all. */
function one(text, tool) {
  const c = S.checkCopy([{ text }], tool);
  return [c.flags.map((f) => f.kind + (f.fixable ? '*' : '')).join(','), S.applyEdits([text], c.fixes)[0]];
}

test('the saved "Sending tool" value: the four choices, anything else is Other', () => {
  assert.equal(S.toolOf('Instantly'), 'Instantly');
  assert.equal(S.toolOf('instantly.ai'), 'Instantly');
  assert.equal(S.toolOf('Smartlead'), 'Smartlead');
  assert.equal(S.toolOf('Pipl'), 'PlusVibe');
  assert.equal(S.toolOf('Lemlist'), 'Other');
  assert.equal(S.toolOf(null), 'Other');
});

test('Instantly: {{RANDOM | a | b}} spintax, camelCase merge fields, a fallback on first name', () => {
  assert.deepEqual(one('{Hey|Hello} there', 'Instantly'), ['spintax*', '{{RANDOM | Hey | Hello}} there']);
  assert.deepEqual(one('{{first_name | there}}', 'Instantly'), ['merge*', '{{firstName | there}}']);
  assert.deepEqual(one('{first_name}', 'Instantly'), ['merge*', '{{firstName}}']);
  assert.deepEqual(one('{{ firstName | there}}', 'Instantly'), ['spaces*', '{{firstName | there}}']);
  assert.deepEqual(one('{{RANDOM|a|b}}', 'Instantly'), ['spaces*', '{{RANDOM | a | b}}']);
  assert.deepEqual(one('{{firstName}}', 'Instantly'), ['fallback', '{{firstName}}']);
  assert.deepEqual(one('{{firstName | there}}', 'Instantly'), ['', '{{firstName | there}}']);
  /* Merge fields are allowed inside spintax. */
  assert.deepEqual(one('{{RANDOM | a {{firstName | there}} | b}}', 'Instantly'), ['', '{{RANDOM | a {{firstName | there}} | b}}']);
});

test('Smartlead: {a|b} spintax, snake_case merge fields, single braces around a name are a mistake', () => {
  assert.deepEqual(one('{{RANDOM | a | b}}', 'Smartlead'), ['spintax*', '{a|b}']);
  assert.deepEqual(one('{{firstName}}', 'Smartlead'), ['merge*', '{{first_name}}']);
  assert.deepEqual(one('{first_name}', 'Smartlead'), ['merge*', '{{first_name}}']);
  assert.match(S.checkCopy([{ text: '{first_name}' }], 'Smartlead').flags[0].why, /spintax by mistake/);
  assert.deepEqual(one('{{ first_name }}', 'Smartlead'), ['spaces*', '{{first_name}}']);
  assert.deepEqual(one('{{first_name}}', 'Smartlead'), ['', '{{first_name}}']);   // no fallback rule
});

test('PlusVibe: one variable per spintax block, an empty option is allowed, Liquid names fields without braces', () => {
  assert.deepEqual(one('{a {{first_name}}|b {{last_name}}}', 'PlusVibe'), ['multi', '{a {{first_name}}|b {{last_name}}}']);
  assert.deepEqual(one('{Hi||Hello}', 'PlusVibe'), ['', '{Hi||Hello}']);
  assert.deepEqual(one('{% if first_name %}Hi {{first_name}}{% endif %}', 'PlusVibe'), ['', '{% if first_name %}Hi {{first_name}}{% endif %}']);
  assert.deepEqual(one('{{firstName}}', 'PlusVibe'), ['merge*', '{{first_name}}']);
});

test('a field the tool does not know is flagged and never guessed', () => {
  for (const tool of ['Instantly', 'Smartlead', 'PlusVibe']) {
    const [flags, fixed] = one('{{industry}}', tool);
    assert.equal(flags, 'unknown', tool);
    assert.equal(fixed, '{{industry}}', tool);
  }
});

test('unbalanced braces: flagged for every tool; Fix all closes a known field only', () => {
  assert.deepEqual(one('{{first_name}', 'Smartlead'), ['braces*', '{{first_name}}']);
  assert.deepEqual(one('{{first_name}', 'Instantly'), ['braces*', '{{firstName}}']);
  assert.deepEqual(one('{a|b', 'Smartlead'), ['braces', '{a|b']);
  assert.deepEqual(one('x }', 'Instantly'), ['braces', 'x }']);
  assert.deepEqual(one('{a|b', 'Other'), ['braces', '{a|b']);
});

test('Other: no tool rules, only the general checks', () => {
  assert.deepEqual(one('{{ first_name }} {Hey|Hello} {{whatever}}', 'Other'), ['', '{{ first_name }} {Hey|Hello} {{whatever}}']);
  assert.equal(S.checkCopy([{ text: 'x' }], 'Other').fixes.length, 0);
});

test('spam words, links and words are counted per email; Subject lines and the email title are not words', () => {
  const body = Array(95).fill('word').join(' ');
  const c = S.checkCopy([
    { text: 'Email 1', heading: true }, { text: 'Subject: a free chat' }, { text: 'See https://a.com and www.b.com today.' },
    { text: 'Email 2' }, { text: body },
  ], 'Other');
  assert.deepEqual(c.emails.map((e) => [e.title, e.words, e.links, e.spam]), [['Email 1', 5, 2, 1], ['Email 2', 95, 0, 0]]);
  assert.deepEqual(c.flags.map((f) => [f.block, f.kind]), [[1, 'spam'], [2, 'links'], [2, 'links']]);
  assert.ok(c.emails[1].words > S.MAX_WORDS);
});

test('Fix all, for every tool: afterwards nothing it could fix is left, and a second Fix all changes nothing', () => {
  const lines = ['Subject: quick question for {{ first_name }}',
    'Hi {first_name}, {Hey|Hello} {{RANDOM | there | friend}}! {{FirstName}} {{company}} {{first_name}',
    '{a {{first_name}}|b {{last_name}}} {% if first_name %}x{% endif %} {{ RANDOM|one|two }}'];
  for (const tool of ['Instantly', 'Smartlead', 'PlusVibe', 'Other']) {
    const c = S.checkCopy(lines.map((text) => ({ text })), tool);
    const fixed = S.applyEdits(lines, c.fixes);
    const again = S.checkCopy(fixed.map((text) => ({ text })), tool);
    assert.equal(again.flags.filter((f) => f.fixable).length, 0, tool + ': ' + JSON.stringify(again.flags));
    assert.equal(again.fixes.length, 0, tool);
    assert.ok(again.flags.some((f) => f.kind === 'unknown') || tool === 'Other', tool + ' still flags {{company}}');
  }
});

/* ---------- Fix all in the editor: one undo step ------------------------------------ */

test('the editor text blocks map to positions, and Fix all is one undo step', () => {
  const schema = new Schema({
    nodes: {
      doc: { content: 'block+' }, text: { group: 'inline' },
      paragraph: { group: 'block', content: 'inline*', toDOM: () => ['p', 0] },
      heading: { group: 'block', content: 'inline*', toDOM: () => ['h2', 0] },
      hardBreak: { group: 'inline', inline: true, toDOM: () => ['br'] },
    },
  });
  const doc = schema.node('doc', null, [
    schema.node('heading', null, [schema.text('Email 1')]),
    schema.node('paragraph', null, [schema.text('Hi {first_name},'), schema.node('hardBreak'), schema.text('{Hey|Hello} there {{company}}')]),
  ]);
  let state = EditorState.create({ doc, plugins: [history()] });
  const blocks = M.blocksOf(state.doc);
  assert.deepEqual(blocks.map((b) => [b.text, b.heading]), [['Email 1', true], ['Hi {first_name},\n{Hey|Hello} there {{company}}', false]]);

  const c = S.checkCopy(blocks.map((b) => ({ text: b.text, heading: b.heading })), 'Instantly');
  const want = S.applyEdits(blocks.map((b) => b.text), c.fixes);
  const tr = M.editsTransaction(state, c.fixes);
  state = state.apply(tr);
  assert.deepEqual(M.blocksOf(state.doc).map((b) => b.text), want);
  assert.equal(want[1], 'Hi {{firstName}},\n{{RANDOM | Hey | Hello}} there {{company}}');

  let after = state;
  assert.ok(undo(state, (t) => { after = state.apply(t); }));
  assert.ok(after.doc.eq(doc), 'one undo puts the whole Fix all back');
});

/* ---------- who may change a document (0015) ------------------------------------- */

test('a card document is for everyone on the team; a client-page document for Owners and Admins only', () => {
  assert.equal(P.canChangeDoc('Member', 'campaigns'), true);
  assert.equal(P.canChangeDoc('Member', null), false);
  assert.equal(P.canChangeDoc('Admin', null), true);
  assert.equal(P.canChangeDoc('Owner', null), true);
  assert.equal(P.canChangeDoc(undefined, null), false);
  assert.equal(P.READ_ONLY, 'Only an Owner or Admin can change this. You can read it.');
});

test('the database refusal (42501) is read as "not allowed", and its own sentence is shown', () => {
  const err = new Error('save_document: HTTP 403 {"code":"42501","details":null,"hint":null,"message":"Only an Owner or Admin can change a client-page document. You can still read it."}');
  assert.ok(P.isDenied(err));
  assert.equal(P.dbMessage(err), 'Only an Owner or Admin can change a client-page document. You can still read it.');
  assert.ok(!P.isDenied(new Error('save_document: HTTP 400 {"message":"document_conflict"}')));
  assert.equal(P.dbMessage(new Error('Failed to fetch')), null);
  assert.equal(P.dbMessage(new Error('x: HTTP 500 <html>')), null);
});

/* ---------- autosave ------------------------------------------------------------------ */

/** A saver with a hand-run clock and a database that answers when told. */
function rig(start = 'v1 text', version = 1) {
  const timers = [];
  const calls = [];
  const statuses = [];
  const saver = new A.DocSaver({
    body: start, version, delay: 1000,
    setTimer: (fn) => { const t = { fn, live: true }; timers.push(t); return t; },
    clearTimer: (t) => { t.live = false; },
    save: (body, v) => new Promise((resolve, reject) => calls.push({ body, v, resolve, reject })),
    onStatus: (s) => statuses.push(s.state),
  });
  const tick = () => { const live = timers.filter((t) => t.live); live.forEach((t) => { t.live = false; t.fn(); }); return live.length; };
  const settle = () => new Promise((r) => setTimeout(r, 0));
  return { saver, calls, statuses, tick, settle };
}

test('autosave: nothing saves while typing; one save 1 second after typing stops, with the last text', async () => {
  const x = rig();
  x.saver.edit('a'); x.saver.edit('ab'); x.saver.edit('abc');
  assert.equal(x.calls.length, 0);
  assert.equal(x.saver.status.state, 'dirty');
  assert.equal(x.tick(), 1, 'only the last timer is live');
  assert.deepEqual(x.calls.map((c) => [c.body, c.v]), [['abc', 1]]);
  assert.equal(x.saver.status.state, 'saving');
  x.calls[0].resolve({ version: 2 });
  await x.settle();
  assert.equal(x.saver.status.state, 'saved');
  assert.equal(x.saver.status.version, 2);
});

test('autosave: typing during a save is saved next, over the new version', async () => {
  const x = rig();
  x.saver.edit('one'); x.tick();
  x.saver.edit('one two');
  x.calls[0].resolve({ version: 2 });
  await x.settle();
  assert.equal(x.saver.status.state, 'dirty');
  x.tick();
  assert.deepEqual(x.calls.map((c) => [c.body, c.v]), [['one', 1], ['one two', 2]]);
  x.calls[1].resolve({ version: 3 });
  await x.settle();
  assert.deepEqual([x.saver.status.state, x.saver.status.version], ['saved', 3]);
  /* The timer fired while a save ran: the next text saves as soon as that save ends. */
  x.saver.edit('one two three'); x.tick();
  x.saver.edit('one two three four'); x.tick();
  assert.equal(x.calls.length, 3);
  x.calls[2].resolve({ version: 4 });
  await x.settle();
  assert.deepEqual(x.calls.map((c) => c.body).slice(2), ['one two three', 'one two three four']);
});

test('autosave: close saves at once; typing back to the saved text saves nothing', async () => {
  const x = rig();
  x.saver.edit('changed');
  const done = x.saver.flush();
  assert.deepEqual(x.calls.map((c) => c.body), ['changed']);
  x.calls[0].resolve({ version: 2 });
  await done;
  assert.equal(x.saver.status.state, 'saved');
  x.saver.edit('changed!'); x.saver.edit('changed');
  assert.equal(x.saver.status.state, 'saved');
  assert.equal(x.tick(), 0);
  await x.saver.flush();
  assert.equal(x.calls.length, 1);
});

test('autosave: a document_conflict stops saving and keeps the text; nothing more is sent', async () => {
  const x = rig();
  x.saver.edit('mine'); x.tick();
  x.calls[0].reject(new Error('save_document: HTTP 400 {"code":"P0001","message":"document_conflict"}'));
  await x.settle();
  assert.equal(x.saver.status.state, 'conflict');
  x.saver.edit('mine, more');
  assert.equal(x.tick(), 0);
  await x.saver.flush();
  assert.equal(x.calls.length, 1);
  assert.equal(x.saver.status.state, 'conflict');
  assert.ok(A.isConflict(new Error('document_conflict')));
  assert.ok(!A.isConflict(new Error('HTTP 500')));
});

test('autosave: any other failure says so, and the next change tries again', async () => {
  const x = rig();
  x.saver.edit('a'); x.tick();
  x.calls[0].reject(new Error('Failed to fetch'));
  await x.settle();
  assert.deepEqual([x.saver.status.state, x.saver.status.error], ['error', 'Failed to fetch']);
  x.saver.edit('ab'); x.tick();
  assert.deepEqual(x.calls.map((c) => [c.body, c.v]), [['a', 1], ['ab', 1]]);
  x.calls[1].resolve({ version: 2 });
  await x.settle();
  assert.equal(x.saver.status.state, 'saved');
});

/* ---------- one line per agency type ----------------------------------------------- */

test('ads: read-aloud time against 15, 30 and 60 second ads', () => {
  const l = D.adScript(75);   // 30 s
  assert.match(l[0].text, /about 30 s/);
  assert.equal(l[1].text, '15 s ad: too long · 30 s ad: fits · 60 s ad: fits');
  assert.equal(D.adScript(200)[1].tone, 'bad');
  assert.equal(D.adScript(30)[1].tone, 'good');
});

test('content: caption length against the platform on the card', () => {
  const text = 'x'.repeat(300);
  const x = D.caption(text, 'X');
  assert.deepEqual(x.map((l) => l.tone), [null, 'bad']);
  assert.match(x[1].text, /20 too many/);
  const ig = D.caption(text, 'Instagram, TikTok');
  assert.deepEqual(ig.slice(1, 3).map((l) => l.tone), ['good', 'good']);
  assert.ok(ig.some((l) => /125 characters/.test(l.text)));
  assert.match(D.caption('short', '')[0].text, /no platform on the card/);
});

test('email marketing: subject line and preview text length', () => {
  const l = D.emailCopy(['Subject: ' + 'a'.repeat(60), 'Preview text: ' + 'b'.repeat(30), 'Body.']);
  assert.deepEqual(l.map((x) => x.tone), ['warn', 'warn']);
  assert.match(l[0].text, /60 characters, over 50/);
  assert.deepEqual(D.emailCopy(['Subject: Hello there', 'Preview: ' + 'c'.repeat(60)]).map((x) => x.tone), ['good', 'good']);
  assert.match(D.emailCopy(['Body only.'])[0].text, /Subject:/);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
