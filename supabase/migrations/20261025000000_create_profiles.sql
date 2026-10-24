-- Account identity lives in Supabase Auth. Large learning content stays on the
-- user's chosen main device; this table is the cloud profile foundation.
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

revoke all on public.profiles from anon;
grant select on public.profiles to authenticated;
grant update (display_name) on public.profiles to authenticated;

create policy "Users read their own profile"
  on public.profiles for select to authenticated
  using ((select auth.uid()) = id);

create policy "Users update their own display name"
  on public.profiles for update to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

create or replace function public.create_subjects_learning_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id) values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke all on function public.create_subjects_learning_profile() from public;

create trigger on_subjects_learning_user_created
  after insert on auth.users
  for each row execute function public.create_subjects_learning_profile();

insert into public.profiles (id)
select id from auth.users
on conflict (id) do nothing;
