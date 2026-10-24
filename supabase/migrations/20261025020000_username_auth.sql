-- Version -3 uses a username in the product. Supabase Auth still holds the
-- password under a deterministic, non-deliverable internal email identifier.
alter table public.profiles
  add column if not exists username text,
  add column if not exists username_key text;

create unique index if not exists profiles_username_key_unique
  on public.profiles (username_key)
  where username_key is not null;

create or replace function public.create_subjects_learning_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  requested_username text;
  internal_email text;
begin
  if new.email like '%@accounts.subjects-learning.invalid' then
    requested_username := new.raw_user_meta_data ->> 'username';
    if requested_username is null
       or char_length(requested_username) not between 3 and 24
       or requested_username <> lower(normalize(requested_username, NFKC)) then
      raise exception 'Invalid username for internal identity';
    end if;
    internal_email := encode(sha256(convert_to(requested_username, 'UTF8')), 'hex')
                      || '@accounts.subjects-learning.invalid';
    if new.email <> internal_email then
      raise exception 'Username does not match internal identity';
    end if;
    insert into public.profiles (id, username, username_key)
      values (new.id, requested_username, split_part(internal_email, '@', 1))
      on conflict (id) do nothing;
  else
    insert into public.profiles (id) values (new.id)
      on conflict (id) do nothing;
  end if;
  return new;
end;
$$;
