/* Tests for the boards of this agency (src/agency.config.ts with src/core.config.ts):
 * the board order per agency type, finished vs live stages, the three-field card face,
 * and the links from one board to another (ads: a creative names its campaign).
 * Node runs the .ts files as they are (Node 22.18 or newer). Run: npm test */
import assert from 'node:assert/strict';
import fs from 'node:fs';

if (!process.features.typescript) {
  console.log('Board tests skipped: they need Node 22.18 or newer (this is ' + process.version + ').');
  process.exit(0);
}
if (!fs.existsSync(new URL('../src/agency.config.ts', import.meta.url))) {
  console.log('Board tests skipped: no src/agency.config.ts here (the template core). The export runs them per agency type.');
  process.exit(0);
}
const CORE = await import('../src/core.config.ts');
const AG = await import('../src/agency.config.ts');
const LADDERS = { ...CORE.CORE_LADDERS, ...AG.LADDERS };
const BOARDS = [CORE.TASKS_BOARD, ...AG.AGENCY.boards];
const RECORDS = BOARDS.concat(AG.AGENCY.lists);
const num = (s) => { const m = /^(-?\d+) - /.exec(s); return m ? Number(m[1]) : null; };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

/* The boards each agency type shows, in tab order (the v2 contract, "Boards per agency type"). */
const ORDER = {
  'Cold Email': ['Tasks', 'Campaigns', 'Inbox set-ups'],
  'Ads': ['Tasks', 'Editing pipeline', 'Campaigns'],
  'Content': ['Tasks', 'Editing pipeline'],
  'Email Marketing': ['Tasks', 'Flows', 'Campaigns'],
};

test('the boards are the ones for this agency type, in order, and no stage table is left as a list', () => {
  const want = ORDER[AG.AGENCY.agency];
  assert.ok(want, 'unknown agency type: ' + AG.AGENCY.agency);
  assert.deepEqual(BOARDS.map((b) => b.label), want);
  assert.deepEqual(AG.AGENCY.lists, []);
});

test('only a "100 - ..." stage is finished (and a below-0 stop such as "-1 - Rejected")', () => {
  RECORDS.forEach((b) => {
    const ladder = LADDERS[b.ladder];
    assert.ok(ladder, b.table + ': no ladder ' + b.ladder);
    b.closed.forEach((s) => {
      assert.ok(ladder.indexOf(s) > -1, b.table + ': finished stage "' + s + '" is not on its ladder');
      assert.ok(num(s) === 100 || num(s) < 0, b.table + ': "' + s + '" is not a 100 stage, so it must stay open');
    });
    ladder.filter((s) => num(s) === 100).forEach((s) => assert.ok(b.closed.indexOf(s) > -1, b.table + ': "' + s + '" must count as finished'));
  });
});

test('a live stage stays open: it is on the ladder and never in the finished list', () => {
  let any = 0;
  RECORDS.forEach((b) => (b.live || []).forEach((s) => {
    any++;
    assert.ok(LADDERS[b.ladder].indexOf(s) > -1, b.table + ': live stage "' + s + '" is not on its ladder');
    assert.equal(b.closed.indexOf(s), -1, b.table + ': live stage "' + s + '" is in the finished list');
  }));
  assert.ok(any > 0, 'every agency type has at least one live stage');
});

test('a card shows its name and three fields at most, each one a field of the board', () => {
  BOARDS.forEach((b) => {
    assert.ok(b.card.length <= 3, b.table + ' shows ' + b.card.length + ' fields on a card');
    const keys = b.sections.flatMap((s) => s.fields.map((f) => f.key));
    b.card.forEach((k) => assert.ok(keys.indexOf(k) > -1, b.table + ': card field ' + k + ' is in no section'));
    b.create.forEach((k) => assert.ok(keys.indexOf(k) > -1, b.table + ': New-form field ' + k + ' is in no section'));
  });
});

test('a link to another card points at a board of this agency', () => {
  BOARDS.forEach((b) => b.sections.forEach((s) => s.fields.forEach((f) => {
    if (f.type !== 'card') return;
    assert.ok(BOARDS.some((x) => x.table === f.board), b.table + '.' + f.key + ' points at ' + f.board + ', which is not a board');
    assert.ok(/_id$/.test(f.key), b.table + '.' + f.key + ' must be an id column');
  })));
});

test('ads: a creative card shows its campaign, and the Campaigns board is the ad_campaigns table', () => {
  if (AG.AGENCY.agency !== 'Ads') return;
  const creatives = BOARDS.find((b) => b.table === 'creatives');
  const link = creatives.sections.flatMap((s) => s.fields).find((f) => f.key === 'ad_campaign_id');
  assert.equal(link.type, 'card');
  assert.equal(link.board, 'ad_campaigns');
  assert.ok(creatives.card.indexOf('ad_campaign_id') > -1, 'the campaign is on the creative card');
  const camp = BOARDS.find((b) => b.label === 'Campaigns');
  assert.equal(camp.table, 'ad_campaigns');
  assert.deepEqual(LADDERS[camp.ladder], ['0 - Backlog', '10 - Planning', '20 - Building', '30 - Client Approval',
    '40 - Ready To Launch', '50 - Live', '60 - Optimising', '100 - Ended']);
  assert.deepEqual(camp.live, ['50 - Live', '60 - Optimising']);
});

test('cold email: inbox set-ups are a board, finished only at "100 - Ready To Send"', () => {
  if (AG.AGENCY.agency !== 'Cold Email') return;
  const b = BOARDS.find((x) => x.table === 'inbox_batches');
  assert.equal(b.label, 'Inbox set-ups');
  assert.deepEqual(b.closed, ['100 - Ready To Send']);
  assert.deepEqual(BOARDS.find((x) => x.table === 'campaigns').live, ['50 - Live']);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed (' + AG.AGENCY.agency + ')');
process.exit(failed ? 1 : 0);
