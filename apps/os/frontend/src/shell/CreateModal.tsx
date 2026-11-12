/* Every "New X" button opens this one form. The fields come from the config: a board's
 * `create` list, the client's CLIENT_CREATE, a call's first fields. It saves the moment you
 * press the button. "Add team member" is its own form (areas/team), because it makes a login. */
import { useState } from 'react';
import type { FieldDef } from '../config';
import { Button, Modal } from '../ui';
import { createOpen, toast } from '../lib/ui';
import { insert, useData } from '../lib/store';
import { listOf, recordDef } from '../lib/schema';
import { navigate, openCard } from '../lib/router';
import { CALL_FIELDS, CLIENT_CREATE } from '../core.config';
import { cardOptions, clientOptions } from '../areas/records/fields';
import { CLIENT_SECTIONS } from '../areas/clients';
import { AddMember } from '../areas/team';

interface Spec { title: string; verb: string; fields: FieldDef[]; after?: (id: string) => void }

function specFor(table: string): Spec | null {
  const def = recordDef(table);
  if (def) {
    const all = def.sections.flatMap((s) => s.fields);
    const fields = def.create.map((k) => all.find((f) => f.key === k)).filter((f): f is FieldDef => !!f)
      .map((f) => (f.key === 'client_id' && def.clientRequired ? { ...f, required: true } : f));
    return { title: 'New ' + def.item, verb: 'Add the ' + def.item, fields, after: (id) => openCard(table, id) };
  }
  if (table === 'clients') {
    const all = CLIENT_SECTIONS.flatMap((s) => s.fields);
    return { title: 'New client', verb: 'Add the client', after: (id) => navigate({ screen: 'client', id }),
      fields: CLIENT_CREATE.map((k) => all.find((f) => f.key === k)).filter((f): f is FieldDef => !!f) };
  }
  if (table === 'calls') {
    return { title: 'Add a call', verb: 'Add the call', fields: CALL_FIELDS.slice(0, 5).map((f) => (f.key === 'title' ? { ...f, required: true } : f)) };
  }
  return null;
}

export function CreateModal() {
  const open = createOpen.use();
  if (!open) return null;
  if (open.table === 'team') return <AddMember onClose={() => createOpen.set(null)} />;
  const spec = specFor(open.table);
  if (!spec) return null;
  return <CreateForm key={open.table} table={open.table} spec={spec} defaults={open.defaults || {}} />;
}

function CreateForm({ table, spec, defaults }: { table: string; spec: Spec; defaults: Record<string, unknown> }) {
  const S = useData();
  const [form, setForm] = useState<Record<string, string>>(() => {
    const f: Record<string, string> = {};
    Object.keys(defaults).forEach((k) => { if (defaults[k] !== null && defaults[k] !== undefined) f[k] = String(defaults[k]); });
    return f;
  });
  const missing = spec.fields.some((f) => f.required && !String(form[f.key] || '').trim());
  const close = () => createOpen.set(null);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  function submit() {
    const row: Record<string, unknown> = { ...defaults };
    spec.fields.forEach((f) => {
      const v = String(form[f.key] ?? '').trim();
      if (v === '') return;
      if (f.type === 'int' || f.type === 'number' || f.type === 'money' || f.type === 'percent') row[f.key] = Number(v);
      else if (f.type === 'month') row[f.key] = v + '-01';
      else if (f.type === 'datetime') row[f.key] = new Date(v).toISOString();
      else if (f.type === 'email') row[f.key] = v.toLowerCase();
      else if (f.type === 'tags') row[f.key] = v.split(',').map((s) => s.trim()).filter(Boolean);
      else row[f.key] = v;
    });
    close();
    insert(table, row).then((made) => { toast('Saved.', 'good'); if (made && spec.after) spec.after(made.id); }).catch(() => {});
  }

  const box = 'w-full h-[36px] rounded-[10px] border border-line bg-card px-3 text-[13px] focus:outline-none focus:border-[var(--border-focus)]';
  const people = S.activeTeam.map((t): [string, string] => [t.id, t.full_name]);
  return (
    <Modal title={spec.title} onClose={close} footer={<>
      <Button variant="primary" disabled={missing} onClick={submit} id="os-create-go">{spec.verb}</Button>
      <Button onClick={close}>Cancel</Button>
      <span className="text-[12px] text-muted ml-auto">It is saved the moment you press this.</span>
    </>}>
      <form className="space-y-3" data-create={table} onSubmit={(e) => { e.preventDefault(); if (!missing) submit(); }}>
        {spec.fields.map((f, i) => {
          const pick = f.type === 'person' ? people : f.type === 'client' ? clientOptions(S)
            : f.type === 'card' ? cardOptions(S, f, { id: '', client_id: form.client_id || null })
            : f.type === 'choice' ? listOf(f.list).map((o): [string, string] => [o, o]) : null;
          const type = f.type === 'date' ? 'date' : f.type === 'datetime' ? 'datetime-local' : f.type === 'month' ? 'month'
            : f.type === 'email' ? 'email' : f.type === 'url' ? 'url'
            : (f.type === 'int' || f.type === 'number' || f.type === 'money' || f.type === 'percent') ? 'number' : 'text';
          return (
            <label key={f.key} className="block">
              <span className="block text-[12.5px] text-muted mb-1">{f.label}{f.required ? '' : ' (optional)'}</span>
              {pick ? (
                <select className={box} value={form[f.key] || ''} onChange={(e) => set(f.key, e.target.value)}>
                  <option value="">{f.required ? 'Pick one' : f.type === 'person' ? 'Nobody yet' : f.type === 'card' ? 'None' : 'Leave blank'}</option>
                  {pick.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              ) : (
                <input className={box} type={type} value={form[f.key] || ''} autoFocus={i === 0} onChange={(e) => set(f.key, e.target.value)} />
              )}
            </label>
          );
        })}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
