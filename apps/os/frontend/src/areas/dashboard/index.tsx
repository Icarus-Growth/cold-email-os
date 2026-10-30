/* Dashboard. It answers three questions, in four layers (filters, scorecards, graphs, tables):
 *   1. What is stuck or late?          v_stuck_cards, v_late_cards
 *   2. Who is overloaded?              v_team_load
 *   3. Which clients need attention?   v_clients_attention
 * The views live in the database (0006_dashboard.sql) and read with the rights of the person
 * asking. "Stuck" is a card that has not moved for settings.stuck_after_days (3 unless you
 * change it on the Team screen). Every number opens the cards behind it. */
import { useState } from 'react';
import { And, BarChart, Button, Card, CardHeader, ClientKey, DataTable, Dot, FilterPill, Modal, Notice, ScoreGrid, Stack, StagePill, type Bar, type Column } from '../../ui';
import { useData, useQuery, type Data, type Row } from '../../lib/store';
import { BOARDS, ladderOf, recordDef } from '../../lib/schema';
import { navigate, openCard } from '../../lib/router';
import { clearScreenFilters, filterValue, screenFilters, setScreenFilter } from '../../lib/ui';
import { shortStage, wait } from '../../lib/format';

const Q = (table: string, order?: string) => ({ key: 'dash:' + table, table, ttl: 0, opts: order ? { order } : {} });

/** One card in a view (v_open_cards and the views made from it), as a table row. */
function cardCols(S: Data): Record<string, Column> {
  return {
    card: { label: 'Card', w: 260, cell: (r) => ({ node: <span className="flex items-center gap-2 min-w-0">
      {r.client_id && <Dot colour={S.clientColour(r.client_id)} size={8} />}<span className="truncate font-medium text-ink">{r.card_name || 'Untitled'}</span></span> }) },
    board: { label: 'Board', w: 140, cell: (r) => ({ t: r.board_label }) },
    client: { label: 'Client', w: 170, cell: (r) => ({ t: r.client_id ? S.clientName(r.client_id) : 'No client' }) },
    who: { label: 'Assignee', w: 150, cell: (r) => ({ t: S.teamName(r.assignee_id) || 'Nobody', tone: r.assignee_id ? null : 'warn' }) },
    stage: { label: 'Stage', w: 170, cell: (r) => ({ node: <StagePill stage={r.stage} /> }) },
    days: { label: 'In this stage', w: 120, align: 'right', cell: (r) => ({ t: wait(r.stage_changed_at), tone: r._stuck ? 'warn' : null }) },
    late: { label: 'Days late', w: 100, align: 'right', cell: (r) => ({ t: r._late ? String(r._late) : '—', tone: r._late ? 'bad' : null }) },
  };
}

function Drill({ S, title, rows, onClose }: { S: Data; title: string; rows: Row[]; onClose: () => void }) {
  return (
    <Modal wide layer="drill" title={title + ' (' + rows.length + ')'} onClose={onClose}>
      <DataTable view="dash:drill" rows={rows} cols={cardCols(S)} defaults={['card', 'client', 'who', 'days']}
        onRowClick={(r) => { onClose(); openCard(r.board, r.card_id); }} empty="Nothing here any more." />
    </Modal>
  );
}

export function Dashboard() {
  const S = useData();
  const f = screenFilters.use();
  const client = filterValue(f, 'dash:client', '');
  const board = filterValue(f, 'dash:board', '');
  const [drill, setDrill] = useState<{ title: string; rows: Row[] } | null>(null);

  const open = useQuery(Q('v_open_cards', 'stage_changed_at.asc'));
  const stuck = useQuery(Q('v_stuck_cards', 'stage_changed_at.asc'));
  const late = useQuery(Q('v_late_cards', 'due_date.asc'));
  const load = useQuery(Q('v_team_load', 'full_name.asc'));
  const attention = useQuery(Q('v_clients_attention', 'client_name.asc'));

  const missing = [open, stuck, late, load, attention].find((q) => q.missing);
  if (missing) {
    return <Notice tone="bad" title="The dashboard views are not in the database yet.">
      Run the database set-up (tab 1) to the end, then open this page again. ({missing.error})
    </Notice>;
  }
  const failed = [open, stuck, late, load, attention].find((q) => q.error);
  if (failed && !failed.rows?.length) return <Notice tone="bad" title="Could not read the dashboard.">{failed.error}</Notice>;
  if (!open.rows || !stuck.rows || !late.rows || !load.rows || !attention.rows) return <Notice title="Loading the dashboard…" />;

  const keep = (r: Row) => (!client || r.client_id === client) && (!board || r.board === board);
  const lateBy: Record<string, number> = {};
  late.rows.forEach((r) => { lateBy[r.board + ':' + r.card_id] = r.days_late; });
  const stuckSet: Record<string, true> = {};
  stuck.rows.forEach((r) => { stuckSet[r.board + ':' + r.card_id] = true; });
  const openRows: Row[] = open.rows.filter(keep).map((r) => ({ ...r, id: r.board + ':' + r.card_id,
    _late: lateBy[r.board + ':' + r.card_id] || 0, _stuck: !!stuckSet[r.board + ':' + r.card_id] }) as Row);
  const problem = openRows.filter((r) => r._late || r._stuck)
    .sort((a, b) => (b._late - a._late) || String(a.stage_changed_at).localeCompare(String(b.stage_changed_at)));
  const stuckRows = openRows.filter((r) => r._stuck);
  const lateRows = openRows.filter((r) => r._late);
  const heldRows = openRows.filter((r) => Number(r.stage_number) % 10 === 9 || Number(r.stage_number) < 0);
  const people: Row[] = load.rows.map((r) => ({ ...r, id: r.team_id }) as Row);
  const over = people.filter((r) => r.overloaded);
  const clients = attention.rows.filter((r) => r.needs_attention && (!client || r.client_id === client)).map((r) => ({ ...r, id: r.client_id }) as Row);
  const days = Number(S.settings.stuck_after_days) || 3;

  // Graph 1: open cards per stage, one chart per board, one colour per client.
  const boards = BOARDS.filter((b) => !board || b.table === board);
  const bars = (table: string): Bar[] => {
    const def = recordDef(table)!;
    return ladderOf(def).filter((s) => def.closed.indexOf(s) < 0).map((stage) => {
      const inStage = openRows.filter((r) => r.board === table && r.stage === stage);
      const byClient: Record<string, number> = {};
      inStage.forEach((r) => { const k = r.client_id || 'none'; byClient[k] = (byClient[k] || 0) + 1; });
      return { key: stage, label: shortStage(stage),
        segments: Object.keys(byClient).map((k) => ({ key: k, n: byClient[k], label: k === 'none' ? 'No client' : S.clientName(k),
          colour: k === 'none' ? 'var(--text-placeholder)' : S.clientColour(k) })) };
    });
  };
  const usedClients = Array.from(new Set(openRows.map((r) => r.client_id).filter(Boolean))) as string[];

  // Graph 2: open cards per person, red when over what they can hold.
  const loadBars: Bar[] = people.map((p) => ({ key: p.team_id, label: p.full_name,
    segments: [{ key: 'n', n: p.open_cards, label: 'Open cards', colour: p.overloaded ? 'var(--bad)' : 'var(--os-c1)' }] }));

  const boardOpts = BOARDS.map((b): [string, string] => [b.table, b.label]);
  return (
    <Stack className="gap-5">
      <div className="flex items-center gap-2 flex-wrap" data-filters>
        <FilterPill label="Client" all="All clients" value={client} options={S.activeClients.map((c): [string, string] => [c.id, c.client_name])}
          onChange={(v) => setScreenFilter('dash:client', v)} />
        <And />
        <FilterPill label="Board" all="All boards" value={board} options={boardOpts} onChange={(v) => setScreenFilter('dash:board', v)} />
        {(client || board) && <Button size="sm" variant="ghost" onClick={() => clearScreenFilters('dash')}>Clear filters</Button>}
      </div>

      <ScoreGrid scores={[
        { label: 'Stuck cards', key: true, value: stuckRows.length, tone: stuckRows.length ? 'bad' : 'good', note: 'Not moved for ' + days + '+ days' },
        { label: 'Late cards', key: true, value: lateRows.length, tone: lateRows.length ? 'bad' : 'good', note: 'Past their due date' },
        { label: 'People overloaded', key: true, value: over.length, tone: over.length ? 'bad' : 'good', note: 'More cards than they can hold' },
        { label: 'Clients needing attention', key: true, value: clients.length, tone: clients.length ? 'bad' : 'good', note: 'Stuck, late, or onboarding stalled' },
        { label: 'Open cards', value: openRows.length, note: 'On every board' },
        { label: 'Held cards', value: heldRows.length, note: 'Sent back or blocked' },
        { label: 'Unassigned cards', value: openRows.filter((r) => !r.assignee_id).length, note: 'Nobody named to act' },
        { label: 'Active clients', value: S.activeClients.length },
      ]} />

      <div className="grid grid-cols-2 max-[1100px]:grid-cols-1 gap-3">
        {boards.map((b) => (
          <Card key={b.table} className="p-5">
            <BarChart title={b.label + ': open cards by stage'} desc="Each colour is one client. Click a bar to see its cards."
              bars={bars(b.table)} labelWidth={150}
              onOpen={() => navigate({ screen: 'tasks', board: b.table })}
              onBarClick={(stage) => setDrill({ title: b.label + ': ' + shortStage(stage), rows: openRows.filter((r) => r.board === b.table && r.stage === stage) })} />
          </Card>
        ))}
        <Card className="p-5">
          <BarChart title="Open cards per person" desc="Red: more open cards than the person can hold. Click a bar to see their cards."
            bars={loadBars} labelWidth={150} onOpen={() => navigate({ screen: 'team' })}
            onBarClick={(id) => setDrill({ title: (S.teamName(id) || 'Person') + ': open cards', rows: openRows.filter((r) => r.assignee_id === id) })} />
        </Card>
      </div>
      {usedClients.length > 0 && <ClientKey items={usedClients.map((id) => ({ key: id, label: S.clientName(id), colour: S.clientColour(id) }))} />}

      <section>
        <CardHeader title="1. What is stuck or late?" desc={'Late cards first, then the cards that have waited longest. Stuck = no move for ' + days + ' days.'} />
        <DataTable view="dash:problems" rows={problem} cols={cardCols(S)} defaults={['card', 'board', 'client', 'who', 'stage', 'days', 'late']}
          rowTone={(r) => (r._late ? 'bad' : 'warn')} onRowClick={(r) => openCard(r.board, r.card_id)} empty="Nothing is stuck or late." />
      </section>

      <section>
        <CardHeader title="2. Who is overloaded?" desc="Open cards per person against how many they can hold." />
        <DataTable view="dash:load" rows={people} defaults={['name', 'open', 'cap', 'late', 'back']}
          cols={{
            name: { label: 'Person', w: 200, cell: (r) => ({ t: r.full_name }) },
            open: { label: 'Open cards', w: 110, align: 'right', cell: (r) => ({ t: String(r.open_cards), tone: r.overloaded ? 'bad' : null }) },
            cap: { label: 'Can hold', w: 100, align: 'right', cell: (r) => ({ t: String(r.capacity) }) },
            late: { label: 'Late', w: 90, align: 'right', cell: (r) => ({ t: String(r.late_cards), tone: r.late_cards ? 'bad' : null }) },
            back: { label: 'Held', w: 90, align: 'right', cell: (r) => ({ t: String(r.sent_back_cards) }) },
          }}
          rowTone={(r) => (r.overloaded ? 'bad' : null)} onRowClick={(r) => navigate({ screen: 'member', id: r.team_id })} empty="Nobody is on the team yet." />
      </section>

      <section>
        <CardHeader title="3. Which clients need attention?" desc="A client with a stuck or late card, or onboarding that has not moved for a while." />
        <DataTable view="dash:clients" rows={clients} defaults={['name', 'am', 'stuck', 'late', 'onb']}
          cols={{
            name: { label: 'Client', w: 220, cell: (r) => ({ node: <span className="flex items-center gap-2"><Dot colour={S.clientColour(r.client_id)} size={8} /><span className="font-medium text-ink truncate">{r.client_name}</span></span> }) },
            am: { label: 'Account manager', w: 170, cell: (r) => ({ t: S.teamName(r.account_manager_id) || 'Nobody' }) },
            stuck: { label: 'Stuck', w: 80, align: 'right', cell: (r) => ({ t: String(r.stuck_cards), tone: r.stuck_cards ? 'warn' : null }) },
            late: { label: 'Late', w: 80, align: 'right', cell: (r) => ({ t: String(r.late_cards), tone: r.late_cards ? 'bad' : null }) },
            onb: { label: 'Onboarding', w: 220, cell: (r) => ({ node: <span className="flex items-center gap-2"><StagePill stage={r.onboarding_stage} />{r.onboarding_stuck && <span className="text-warn text-[12px]">not moving</span>}</span> }) },
          }}
          onRowClick={(r) => navigate({ screen: 'client', id: r.client_id })} empty="Every client is on track." />
      </section>

      {drill && <Drill S={S} title={drill.title} rows={drill.rows} onClose={() => setDrill(null)} />}
    </Stack>
  );
}
