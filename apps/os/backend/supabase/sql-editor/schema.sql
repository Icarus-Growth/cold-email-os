-- Paste this into the Supabase SQL editor and press Run.
-- Send the result to your AI. It writes SCHEMAS.md from it.

select (case when t.table_type = 'VIEW' then 'view column' else 'table column' end)::text as kind,
       c.table_name::text as name, c.column_name::text as detail,
       case when c.data_type = 'USER-DEFINED' then c.udt_name
            when c.data_type = 'ARRAY' then ltrim(c.udt_name, '_') || '[]'
            else c.data_type end as data_type,
       coalesce(col_description(format('public.%I', c.table_name)::regclass, c.ordinal_position), '') as note,
       c.ordinal_position as pos
from information_schema.columns c
join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name
where c.table_schema = 'public'
union all
select 'list', t.typname::text, string_agg(e.enumlabel::text, ', ' order by e.enumsortorder), '', '', 0
from pg_type t join pg_enum e on e.enumtypid = t.oid
join pg_namespace n on n.oid = t.typnamespace
where n.nspname = 'public' group by t.typname
order by 1, 2, 6;
