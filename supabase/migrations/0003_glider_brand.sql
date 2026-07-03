-- SKORE — split glider into brand + wing name (builds on 0001/0002).
--
-- Adds `glider_brand`; the existing `glider` column now holds the wing NAME (날개명).
-- Backward-compatible: existing rows keep their full string in `glider` with an empty
-- brand, so display (brand + " " + name) is unchanged. Idempotent.

alter table public.roster   add column if not exists glider_brand text not null default '';
alter table public.profiles add column if not exists glider_brand text not null default '';

-- Signup trigger: also copy glider_brand from the signUp metadata.
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
    pilot_name, bib, glider, glider_brand, glider_class, contact
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
    coalesce(new.raw_user_meta_data->>'glider_brand', ''),
    coalesce(new.raw_user_meta_data->>'glider_class', ''),
    coalesce(new.raw_user_meta_data->>'contact', '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
