/* Tests for My Work's who-acts-next (src/areas/home/work.ts), the Tasks "Me" default
 * (src/areas/tasks/assignee.ts), the client page's buttons (src/areas/clients/actions.ts) and
 * "added ... ago" (src/lib/format.ts). Node runs the .ts files as they are (Node 22.18 or newer).
 * Run: npm test */
import assert from 'node:assert/strict';
import fs from 'node:fs';

if (!process.features.typescript) {
  console.log('My Work tests skipped: they need Node 22.18 or newer (this is ' + process.version + ').');
  process.exit(0);
}
const W = await import('../src/areas/home/work.ts');
const A = await import('../src/areas/tasks/assignee.ts');
const C = await import('../src/areas/clients/actions.ts');
const F = await import('../src/lib/format.ts');

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const OWNER = { id: 'o1', full_name: 'Olive Owner', access: 'Owner', status: 'Active' };
const AM = { id: 'am', full_name: 'Ana Manager', access: 'Admin', status: 'Active' };
const ED = { id: 'ed', full_name: 'Eddie Editor', access: 'Member', status: 'Active' };
const REV = { id: 'rv', full_name: 'Rita Reviewer', access: 'Member', status: 'Active' };
const TEAM = [OWNER, AM, ED, REV];

const TASKS = { table: 'tasks', label: 'Tasks', item: 'task', nameKey: 'task_name', stageKey: 'stage', closed: ['100 - Complete', '-1 - Rejected'] };
const VIDEOS = { table: 'videos', label: 'Videos', item: 'video', nameKey: 'video_title', stageKey: 'stage', closed: ['100 - Posted'], live: ['60 - Scheduled'] };

/* The same shape as alert_rules.json: a "new card" rule for every board, then stage rules. */
const RULES = [
  { board: '*', when: 'new', tag: ['assignee', 'client.account_manager_id', 'owner'] },
  { board: 'tasks', to: ['9 - Blocked'], tag: ['client.account_manager_id', 'owner'] },
  { board: 'tasks', to: ['30 - In Review'], tag: ['reviewer', 'client.account_manager_id', 'owner'] },
  { board: 'videos', to: ['40 - Client Review'], tag: ['client.account_manager_id', 'owner'] },
  { board: '*', to: ['50 - Ready To Post'], tag: ['client.social_media_manager_id'] },
];

const CLIENTS = { c1: { id: 'c1', client_name: 'Acme', account_manager_id: 'am' }, c2: { id: 'c2', client_name: 'Bolt' } };

function src(rows, extra) {
  return { boards: [TASKS, VIDEOS], rows: (t) => rows[t] || [], clientById: CLIENTS, team: TEAM, rules: RULES, today: '2026-10-28', ...(extra || {}) };
}
const task = (id, stage, more) => ({ id, task_name: 'Task ' + id, stage, client_id: 'c1', ...(more || {}) });

test('the rule for the stage decides; a stage with no rule uses the "new card" rule', () => {
  assert.deepEqual(W.tagsFor(RULES, 'tasks', '30 - In Review'), ['reviewer', 'client.account_manager_id', 'owner']);
  assert.deepEqual(W.tagsFor(RULES, 'tasks', '10 - In Progress'), ['assignee', 'client.account_manager_id', 'owner']);
  assert.deepEqual(W.tagsFor(RULES, 'videos', '50 - Ready To Post'), ['client.social_media_manager_id']);
  assert.deepEqual(W.tagsFor([], 'tasks', '10 - In Progress'), ['assignee']);
});

test('who acts: the assignee on an open stage, the reviewer in review', () => {
  const s = src({});
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { assignee_id: 'ed', reviewer_id: 'rv' }), '10 - In Progress'), 'ed');
  assert.equal(W.whoActs(s, 'tasks', task('t', '30 - In Review', { assignee_id: 'ed', reviewer_id: 'rv' }), '30 - In Review'), 'rv');
});

test('who acts: no assignee or reviewer falls to the client\'s account manager, then the Owner', () => {
  const s = src({});
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress'), '10 - In Progress'), 'am');
  assert.equal(W.whoActs(s, 'tasks', task('t', '30 - In Review', { assignee_id: 'ed' }), '30 - In Review'), 'am');
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { client_id: 'c2' }), '10 - In Progress'), 'o1');
  assert.equal(W.whoActs(s, 'tasks', task('t', '9 - Blocked', { assignee_id: 'ed' }), '9 - Blocked'), 'am');
});

test('who acts: nobody when no one the rule names is filled in, or the person is not on the team', () => {
  const s = src({}, { team: [AM, ED, REV] });   // no Owner
  assert.equal(W.whoActs(s, 'videos', { id: 'v', client_id: 'c2', stage: '50 - Ready To Post' }, '50 - Ready To Post'), null);
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { client_id: 'c2' }), '10 - In Progress'), null);
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { client_id: 'c2', assignee_id: 'gone' }), '10 - In Progress'), null);
});

test('the Owner fallback skips an Owner who is not Active', () => {
  const s = src({}, { team: [{ ...OWNER, status: 'Inactive' }, { id: 'o2', full_name: 'Zed Owner', access: 'Owner', status: 'Active' }] });
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { client_id: 'c2' }), '10 - In Progress'), 'o2');
});

test('open work leaves out finished stages, and reads due, late, since and moved-by', () => {
  const all = W.openWork(src({ tasks: [
    task('a', '10 - In Progress', { assignee_id: 'ed', due_date: '2026-10-27', stage_changed_at: '2026-10-20T09:00:00Z', stage_changed_by_id: 'am' }),
    task('b', '100 - Complete', { assignee_id: 'ed' }),
    task('c', '-1 - Rejected', { assignee_id: 'ed' }),
  ] }));
  assert.deepEqual(all.map((w) => w.id), ['a']);
  const a = all[0];
  assert.deepEqual([a.board, a.name, a.waiter, a.due, a.late, a.since, a.lastBy], ['Tasks', 'Task a', 'ed', '2026-10-27', true, '2026-10-20T09:00:00Z', 'am']);
  const today = W.openWork(src({ tasks: [task('d', '10 - In Progress', { due_date: '2026-10-28' })] }))[0];
  assert.equal(today.late, false);
});

test('a live card stays on My Work, is never late, and comes after the work that waits', () => {
  const all = W.openWork(src({
    videos: [
      { id: 'live-old-due', video_title: 'V1', stage: '60 - Scheduled', client_id: 'c1', assignee_id: 'ed', due_date: '2026-09-01' },
      { id: 'posted', video_title: 'V2', stage: '100 - Posted', client_id: 'c1', assignee_id: 'ed' },
    ],
    tasks: [task('fresh', '10 - In Progress', { assignee_id: 'ed', due_date: '2026-12-01' })],
  }));
  assert.deepEqual(all.map((w) => w.id).sort(), ['fresh', 'live-old-due']);
  const live = all.find((w) => w.id === 'live-old-due');
  assert.deepEqual([live.live, live.late], [true, false]);
  assert.deepEqual(W.waitsOnYou(all, 'ed').map((w) => w.id), ['fresh', 'live-old-due']);
});

test('a board with liveOnMyWork: false keeps its live cards off My Work; other boards keep theirs', () => {
  const FLOWS = { table: 'flows', label: 'Flows', item: 'flow', nameKey: 'flow_name', stageKey: 'stage', closed: ['100 - Retired'], live: ['60 - Live'], liveOnMyWork: false };
  const s = src({
    flows: [
      { id: 'flow-live', flow_name: 'Welcome', stage: '60 - Live', client_id: 'c1', assignee_id: 'ed', due_date: '2026-09-01', stage_changed_by_id: 'am' },
      { id: 'flow-build', flow_name: 'Winback', stage: '20 - Copy', client_id: 'c1', assignee_id: 'ed' },
      { id: 'flow-retired', flow_name: 'Old cart', stage: '100 - Retired', client_id: 'c1', assignee_id: 'ed' },
    ],
    videos: [{ id: 'video-live', video_title: 'V1', stage: '60 - Scheduled', client_id: 'c1', assignee_id: 'ed' }],
  });
  s.boards = s.boards.concat([FLOWS]);
  const all = W.openWork(s);
  assert.deepEqual(all.map((w) => w.id).sort(), ['flow-build', 'video-live']);
  assert.deepEqual(W.waitsOnYou(all, 'ed').map((w) => w.id), ['flow-build', 'video-live']);
  assert.deepEqual(W.waitsOnOthers(all, 'am').map((w) => w.id), []);
});

test('a due date on a live or finished card is a plain date, never "Late since"', () => {
  const past = '2020-01-15';
  assert.deepEqual(F.dueLine(past), { text: 'Late since 15 Jan', tone: 'bad', late: true });
  assert.deepEqual(F.dueLine(past, 'Due', false), { text: 'Due 15 Jan', tone: null, late: false });
  assert.equal(F.dueLine('2099-01-15', 'Due', false).text, 'Due 15 Jan');
});

test('waits on you: late first, then due soonest, then longest in its stage', () => {
  const all = W.openWork(src({ tasks: [
    task('later', '10 - In Progress', { assignee_id: 'ed', due_date: '2026-11-10' }),
    task('none-new', '10 - In Progress', { assignee_id: 'ed', stage_changed_at: '2026-10-27T09:00:00Z' }),
    task('late', '10 - In Progress', { assignee_id: 'ed', due_date: '2026-10-01' }),
    task('soon', '10 - In Progress', { assignee_id: 'ed', due_date: '2026-10-29' }),
    task('none-old', '10 - In Progress', { assignee_id: 'ed', stage_changed_at: '2026-10-01T09:00:00Z' }),
    task('theirs', '10 - In Progress', { assignee_id: 'rv' }),
  ] }));
  assert.deepEqual(W.waitsOnYou(all, 'ed').map((w) => w.id), ['late', 'soon', 'later', 'none-old', 'none-new']);
});

test('waits on others: what I hold or moved last that now waits on someone else, and never my own', () => {
  const all = W.openWork(src({ tasks: [
    task('in-review', '30 - In Review', { assignee_id: 'ed', reviewer_id: 'rv', stage_changed_at: '2026-10-25T09:00:00Z', stage_changed_by_id: 'ed' }),
    task('sent-back', '29 - Amendments', { assignee_id: 'ed', reviewer_id: 'rv', stage_changed_at: '2026-10-26T09:00:00Z', stage_changed_by_id: 'rv' }),
    task('blocked', '9 - Blocked', { assignee_id: 'ed', stage_changed_at: '2026-10-24T09:00:00Z' }),
    task('not-yet', '10 - In Progress', { assignee_id: 'ed', reviewer_id: 'rv' }),
  ] }, { team: [ED, REV] }));
  assert.deepEqual(W.waitsOnOthers(all, 'ed').map((w) => [w.id, w.waiter]), [['blocked', null], ['in-review', 'rv']]);
  assert.deepEqual(W.waitsOnOthers(all, 'rv').map((w) => [w.id, w.waiter]), [['sent-back', 'ed']]);
  assert.deepEqual(W.waitsOnYou(all, 'rv').map((w) => w.id), ['in-review']);
});

test('since yesterday counts moves on my cards: moved, finished, sent back (new cards are not moves)', () => {
  const s = src({ tasks: [task('a', '30 - In Review', { assignee_id: 'ed' }), task('b', '10 - In Progress', { reviewer_id: 'ed' }), task('x', '10 - In Progress', { assignee_id: 'rv' })] });
  const moves = [
    { board: 'tasks', record_id: 'a', from_stage: '10 - In Progress', to_stage: '30 - In Review' },
    { board: 'tasks', record_id: 'a', from_stage: '30 - In Review', to_stage: '29 - Amendments' },
    { board: 'tasks', record_id: 'b', from_stage: '30 - In Review', to_stage: '100 - Complete' },
    { board: 'tasks', record_id: 'b', from_stage: null, to_stage: '0 - Backlog' },
    { board: 'tasks', record_id: 'x', from_stage: '0 - Backlog', to_stage: '10 - In Progress' },
    { board: 'videos', record_id: 'a', from_stage: '10 - Ready To Edit', to_stage: '30 - Internal Review' },
  ];
  assert.deepEqual(W.sinceYesterday(s, moves, 'ed'), { moved: 3, finished: 1, sentBack: 1 });
});

test('the real alert rules (when this repo has them): a task in review waits on its reviewer', () => {
  const file = new URL('../../automations/alert_rules.json', import.meta.url);
  if (!fs.existsSync(file)) return;
  const rules = JSON.parse(fs.readFileSync(file, 'utf8')).rules;
  const s = src({}, { rules });
  assert.equal(W.whoActs(s, 'tasks', task('t', '30 - In Review', { assignee_id: 'ed', reviewer_id: 'rv' }), '30 - In Review'), 'rv');
  assert.equal(W.whoActs(s, 'tasks', task('t', '10 - In Progress', { assignee_id: 'ed', reviewer_id: 'rv' }), '10 - In Progress'), 'ed');
});

test('Tasks Assignee filter: Me by default, Everyone for someone not on the team', () => {
  assert.equal(A.assigneeChoice(undefined, 'ed'), 'me');
  assert.equal(A.assigneeId(undefined, 'ed'), 'ed');
  assert.equal(A.assigneeChoice(undefined, null), '');
  assert.equal(A.assigneeChoice('me', null), '');
  assert.equal(A.assigneeId('', 'ed'), '', 'Everyone, once picked, stays Everyone');
  assert.equal(A.assigneeId('rv', 'ed'), 'rv');
  assert.equal(A.assigneeKey('tasks'), 'tasks:tasks:person');
});

test('Tasks Assignee filter: the cards and the counts follow the same choice', () => {
  const rows = [task('a', '10 - In Progress', { assignee_id: 'ed' }), task('b', '10 - In Progress', { assignee_id: 'rv' }),
    task('c', '100 - Complete', { assignee_id: 'ed' }), task('d', '10 - In Progress')];
  assert.deepEqual(rows.filter((r) => A.passesAssignee(r, undefined, 'ed')).map((r) => r.id), ['a', 'c']);
  assert.equal(A.openCount(TASKS, rows, undefined, 'ed'), 1);
  assert.equal(A.openCount(TASKS, rows, '', 'ed'), 3);
  assert.equal(A.openCount(TASKS, rows, 'rv', 'ed'), 1);
  assert.equal(A.openCount(TASKS, rows, undefined, null), 3);
});

test('View as: an Owner or Admin picks anyone (themselves first); a Member sees only their own work', () => {
  const names = (w) => w.options;
  const admin = W.whoseWork(AM, TEAM, '');
  assert.equal(admin.canPick, true);
  assert.equal(admin.person.id, 'am');
  assert.deepEqual(names(admin), ['Ana Manager', 'Olive Owner', 'Eddie Editor', 'Rita Reviewer']);
  assert.equal(W.whoseWork(AM, TEAM, 'Eddie Editor').person.id, 'ed');
  assert.equal(W.whoseWork(OWNER, TEAM, 'Rita Reviewer').person.id, 'rv');
  assert.equal(W.whoseWork(OWNER, TEAM, 'Someone who left').person.id, 'o1', 'a name not on the list falls back to yourself');
  const member = W.whoseWork(ED, TEAM, 'Olive Owner');
  assert.deepEqual([member.canPick, member.person.id, member.options.length], [false, 'ed', 0], 'a remembered pick does not count for a Member');
  const outsider = W.whoseWork(null, TEAM, '');
  assert.deepEqual([outsider.canPick, outsider.person.id], [true, 'o1']);
});

test('client page: a Member sees no Delete, Archive or Restore; an Owner or Admin sees them', () => {
  assert.deepEqual(C.clientActions(false, false), []);
  assert.deepEqual(C.clientActions(false, true), []);
  assert.deepEqual(C.clientActions(true, false), ['archive', 'delete']);
  assert.deepEqual(C.clientActions(true, true), ['restore', 'delete']);
});

test('"added ... ago": no "just now ago", and nothing when there is no date', () => {
  const at = (ms) => new Date(Date.now() - ms).toISOString();
  assert.equal(F.ago(at(60e3)), 'just now');
  assert.equal(F.ago(at(5 * 3600e3 + 60e3)), '5h ago');
  assert.equal(F.ago(at(3 * 86400e3 + 60e3)), '3d ago');
  assert.equal(F.ago(null), '');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
