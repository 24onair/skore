-- SKORE — account approval + super-admin (builds on 0001_init.sql)
--
-- Adds an `admin` role and an account-level `status` gate. New self-selected
-- organizers land `pending` and cannot create leagues until a super-admin approves;
-- participants and admins are `active` (participants are still gated per-league by
-- roster.status, so no double approval). Idempotent — safe to re-run.

-- --- role + status columns -------------------------------------------------
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles
  add constraint profiles_role_check check (role in ('organizer', 'participant', 'admin'));

alter table public.profiles
  add column if not exists status text not null default 'active';
alter table public.profiles drop constraint if exists profiles_status_check;
alter table public.profiles
  add constraint profiles_status_check check (status in ('active', 'pending', 'rejected'));

-- --- signup trigger: organizers start pending; bootstrap the super-admin ----
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_role  text    := coalesce(nullif(new.raw_user_meta_data->>'role', ''), 'participant');
  v_admin boolean := lower(new.email) = '24onair@gmail.com';
begin
  insert into public.profiles (
    id, email, display_name, role, status,
    pilot_name, bib, glider, glider_class, contact
  ) values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'display_name', ''),
    case when v_admin then 'admin' else v_role end,
    case when v_admin then 'active'
         when v_role = 'organizer' then 'pending'
         else 'active' end,
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

-- --- backfill / seed (idempotent) ------------------------------------------
-- Column default 'active' already grandfathers every existing account, so nobody
-- is locked out. Explicitly keep league owners active, and seed the super-admin.
update public.profiles p set status = 'active'
  where role = 'organizer'
    and exists (select 1 from public.leagues l where l.owner_id = p.id);

update public.profiles set role = 'admin', status = 'active'
  where lower(email) = '24onair@gmail.com';
