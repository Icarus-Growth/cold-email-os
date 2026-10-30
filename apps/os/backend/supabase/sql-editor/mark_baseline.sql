-- Paste this into the Supabase SQL editor and press Run (SQL editor way, Step 10).
-- Your AI puts the starting file's number in place of <YYYYMMDDHHMMSS> first.
-- It records that the starting file has already run, so the database tool
-- (supabase db push) does not run it again. Same table shape the tool makes.

create schema if not exists supabase_migrations;
create table if not exists supabase_migrations.schema_migrations (version text not null primary key);
alter table supabase_migrations.schema_migrations add column if not exists statements text[];
alter table supabase_migrations.schema_migrations add column if not exists name text;

insert into supabase_migrations.schema_migrations (version, name)
values ('<YYYYMMDDHHMMSS>', 'baseline')
on conflict (version) do nothing;

select version, name from supabase_migrations.schema_migrations order by version;
