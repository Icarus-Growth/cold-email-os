-- Paste this into the Supabase SQL editor and press Run.
-- One table comes back. Every "locked", "reads as person asking" and
-- "stranger sees" line must show the good answer.

create or replace function pg_temp.seen_by(who text) returns table(table_name text, rows_seen bigint)
language plpgsql as $f$
declare t text; n bigint;
begin
  perform set_config('request.jwt.claims', json_build_object('email', who, 'role', 'authenticated')::text, false);
  perform set_config('role', 'authenticated', false);
  for t in select c.relname from pg_class c join pg_namespace s on s.oid = c.relnamespace
           where s.nspname = 'public' and c.relkind in ('r', 'v') order by 1 loop
    begin
      execute format('select count(*) from public.%I', t) into n;
    exception when insufficient_privilege then n := 0;
    end;
    table_name := t; rows_seen := n; return next;
  end loop;
  perform set_config('role', 'none', false);
  perform set_config('request.jwt.claims', '', false);
end
$f$;

select 'table locked' as check_name, c.relname as name,
       case when c.relrowsecurity then 'yes' else 'NO' end as result
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
union all
select 'view reads as person asking', c.relname,
       case when coalesce(array_to_string(c.reloptions, ',') like '%security_invoker=true%', false) then 'yes' else 'NO' end
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'v'
union all
select 'stage log on', tgrelid::regclass::text, 'yes'
from pg_trigger where tgname like '%\_log\_stage'
union all
select 'mover kept on repeat move', s.tgrelid::regclass::text,
       case when exists (select 1 from pg_trigger m where m.tgrelid = s.tgrelid and m.tgname like '%\_log\_mover') then 'yes' else 'NO' end
from pg_trigger s where s.tgname like '%\_log\_stage'
union all
select 'only Owner or Admin deletes', p.relname,
       case when exists (select 1 from pg_trigger g where g.tgrelid = p.oid and g.tgname like '%\_delete\_admin\_only') then 'yes' else 'NO' end
from pg_class p
where p.relnamespace = 'public'::regnamespace and p.relname <> 'team'
  and exists (select 1 from pg_constraint k where k.confrelid = p.oid and k.contype = 'f' and k.confdeltype = 'c')
union all
select 'stranger sees', table_name, case when rows_seen = 0 then '0 rows (good)' else rows_seen || ' rows (BAD)' end
from pg_temp.seen_by('someone-not-on-the-team@example.com')
order by 1, 2;
