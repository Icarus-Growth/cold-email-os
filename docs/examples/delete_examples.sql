-- =============================================================================
-- Delete every example row (is_example = true), in every table that has one.
--
-- Safe stop: deleting an example client also deletes the work under it. So if
-- any REAL row (is_example = false) points at an example client, this stops
-- and says where, and nothing is deleted. Move that work to a real client first.
-- =============================================================================

do $del$
declare
  t      text;
  n      bigint;
  found  text := '';
begin
  -- 1. Look for real rows that point at an example client.
  for t in
    select c.table_name from information_schema.columns c
    join information_schema.tables tb on tb.table_schema = c.table_schema and tb.table_name = c.table_name
    where c.table_schema = 'public' and c.column_name = 'client_id' and tb.table_type = 'BASE TABLE'
      and c.table_name <> 'stage_log'
      and exists (select 1 from information_schema.columns x
                  where x.table_schema = 'public' and x.table_name = c.table_name and x.column_name = 'is_example')
  loop
    execute format('select count(*) from public.%I r join public.clients c on c.id = r.client_id '
                   'where c.is_example and not r.is_example', t) into n;
    if n > 0 then
      found := found || format('%s: %s row(s); ', t, n);
    end if;
  end loop;
  if found <> '' then
    raise exception 'Stopped. Real rows point at an example client: %', found
      using hint = 'Move them to a real client, then run this file again.';
  end if;

  -- 2. Delete examples everywhere except clients and team.
  for t in
    select c.table_name from information_schema.columns c
    join information_schema.tables tb on tb.table_schema = c.table_schema and tb.table_name = c.table_name
    where c.table_schema = 'public' and c.column_name = 'is_example' and tb.table_type = 'BASE TABLE'
      and c.table_name not in ('clients', 'team')
  loop
    execute format('delete from public.%I where is_example', t);
  end loop;

  -- 3. The log rows about example clients, then the example clients, then the example people.
  delete from public.stage_log where client_id in (select id from public.clients where is_example);
  delete from public.clients where is_example;
  delete from public.team where is_example;
end
$del$;

-- Read back: this should list every table with 0.
select 'team' as table_name, count(*) as example_rows from public.team where is_example
union all select 'clients', count(*) from public.clients where is_example
union all select 'stage_log', count(*) from public.stage_log where is_example;
