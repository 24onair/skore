-- SKORE — initial schema (Supabase Postgres)
-- profiles / leagues / meets / tasks / roster + signup trigger + RLS + IGC storage bucket.
--
-- Run this in the Supabase SQL editor (or `supabase db push`). Idempotent-ish: safe to
-- re-run. The backend connects with the service_role (bypasses RLS) and enforces
-- authorization in-app (require_owner); RLS below is a second safety net for any
-- direct PostgREST access with the anon key.

-- ---------------------------------------------------------------------------
-- profiles: 1:1 with auth.users — role + pilot profile (glider/class/contact)
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text,
  display_name  text not null default '',
  role          text not null default 'participant' check (role in ('organizer','participant')),
  pilot_name    text not null default '',
  bib           text not null default '',
  glider        text not null default '',
  glider_class  text not null default '',   -- CCC / D / C / B / A  ('' = 미지정)
  contact       text not null default '',
  created       timestamptz not null default now()
);

-- Auto-create a profile whenever a new auth user signs up. The frontend passes
-- display_name/role/pilot_name/bib/glider/glider_class/contact via signUp options.data,
-- which lands in auth.users.raw_user_meta_data.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (
    id, email, display_name, role, pilot_name, bib, glider, glider_class, contact
  ) values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'display_name', ''),
    coalesce(nullif(new.raw_user_meta_data->>'role',''), 'participant'),
    coalesce(new.raw_user_meta_data->>'pilot_name', ''),
    coalesce(new.raw_user_meta_data->>'bib', ''),
    coalesce(new.raw_user_meta_data->>'glider', ''),
    coalesce(new.raw_user_meta_data->>'glider_class', ''),
    coalesce(new.raw_user_meta_data->>'contact', '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- leagues > meets > tasks   (+ league-level roster)
-- ---------------------------------------------------------------------------
create table if not exists public.leagues (
  id        uuid primary key default gen_random_uuid(),
  owner_id  uuid references auth.users(id) on delete set null,
  name      text not null default 'Untitled league',
  params    jsonb not null default '{}'::jsonb,      -- default scoring params
  created   timestamptz not null default now()
);

create table if not exists public.meets (
  id         uuid primary key default gen_random_uuid(),
  league_id  uuid not null references public.leagues(id) on delete cascade,
  name       text not null default '',
  params     jsonb not null default '{}'::jsonb,      -- per-meet scoring params
  ord        int not null default 0,
  created    timestamptz not null default now()
);
create index if not exists meets_league_idx on public.meets(league_id);

create table if not exists public.tasks (
  id       uuid primary key default gen_random_uuid(),
  meet_id  uuid not null references public.meets(id) on delete cascade,
  name     text not null default '',
  result   jsonb not null default '{}'::jsonb,        -- scored snapshot (computed)
  ord      int not null default 0,
  created  timestamptz not null default now()
);
create index if not exists tasks_meet_idx on public.tasks(meet_id);

create table if not exists public.roster (
  id            uuid primary key default gen_random_uuid(),
  league_id     uuid not null references public.leagues(id) on delete cascade,
  uid           uuid references auth.users(id) on delete set null,  -- linked account (self-registration)
  bib           text not null default '',
  name          text not null default '',
  glider        text not null default '',
  glider_class  text not null default '',
  aliases       jsonb not null default '[]'::jsonb,
  contact       text not null default '',
  source        text not null default 'organizer',   -- organizer | igc | self
  status        text not null default 'approved',     -- approved | pending | rejected
  created       timestamptz not null default now()
);
create index if not exists roster_league_idx on public.roster(league_id);
create index if not exists roster_uid_idx on public.roster(uid);

-- ---------------------------------------------------------------------------
-- Row Level Security (defense-in-depth; backend uses service_role)
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.leagues  enable row level security;
alter table public.meets    enable row level security;
alter table public.tasks    enable row level security;
alter table public.roster   enable row level security;

-- profiles: a user manages only their own row
drop policy if exists profiles_self_rw on public.profiles;
create policy profiles_self_rw on public.profiles
  for all using (id = auth.uid()) with check (id = auth.uid());

-- leagues: any authenticated user may read (standings); only the owner may write
drop policy if exists leagues_read on public.leagues;
create policy leagues_read on public.leagues
  for select using (auth.role() = 'authenticated');
drop policy if exists leagues_owner_write on public.leagues;
create policy leagues_owner_write on public.leagues
  for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- meets: read if authenticated; write only if you own the parent league
drop policy if exists meets_read on public.meets;
create policy meets_read on public.meets
  for select using (auth.role() = 'authenticated');
drop policy if exists meets_owner_write on public.meets;
create policy meets_owner_write on public.meets
  for all
  using (exists (select 1 from public.leagues l where l.id = meets.league_id and l.owner_id = auth.uid()))
  with check (exists (select 1 from public.leagues l where l.id = meets.league_id and l.owner_id = auth.uid()));

-- tasks: read if authenticated; write only if you own the league (via meet)
drop policy if exists tasks_read on public.tasks;
create policy tasks_read on public.tasks
  for select using (auth.role() = 'authenticated');
drop policy if exists tasks_owner_write on public.tasks;
create policy tasks_owner_write on public.tasks
  for all
  using (exists (
    select 1 from public.meets m join public.leagues l on l.id = m.league_id
    where m.id = tasks.meet_id and l.owner_id = auth.uid()))
  with check (exists (
    select 1 from public.meets m join public.leagues l on l.id = m.league_id
    where m.id = tasks.meet_id and l.owner_id = auth.uid()));

-- roster: owner-only for BOTH read and write (contact is private; non-owners get the
-- roster through the backend API, which strips contact and hides pending entries)
drop policy if exists roster_owner_all on public.roster;
create policy roster_owner_all on public.roster
  for all
  using (exists (select 1 from public.leagues l where l.id = roster.league_id and l.owner_id = auth.uid()))
  with check (exists (select 1 from public.leagues l where l.id = roster.league_id and l.owner_id = auth.uid()));
-- a participant may also see their OWN roster entries (join status on the dashboard)
drop policy if exists roster_self_read on public.roster;
create policy roster_self_read on public.roster
  for select using (uid = auth.uid());

-- ---------------------------------------------------------------------------
-- Storage: private bucket for uploaded IGC tracks
-- (backend reads with service_role; browsers upload their own files)
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('igc', 'igc', false)
on conflict (id) do nothing;

drop policy if exists "igc authenticated upload" on storage.objects;
create policy "igc authenticated upload" on storage.objects
  for insert to authenticated with check (bucket_id = 'igc');

drop policy if exists "igc authenticated read" on storage.objects;
create policy "igc authenticated read" on storage.objects
  for select to authenticated using (bucket_id = 'igc');
