-- A small, private directory of data held on each user's device.
-- Neither complete question content nor file bytes belong in these tables.
create table public.learning_inventory (
  user_id uuid not null references auth.users (id) on delete cascade,
  device_id uuid not null,
  counts jsonb not null default '{}'::jsonb,
  manifest_sha256 text not null check (length(manifest_sha256) = 64),
  indexed_at timestamptz not null default now(),
  primary key (user_id, device_id)
);

create table public.learning_catalog (
  user_id uuid not null references auth.users (id) on delete cascade,
  device_id uuid not null,
  kind text not null check (kind in ('question', 'paper', 'knowledge', 'node', 'asset', 'word')),
  local_id text not null check (length(local_id) between 1 and 100),
  title text not null default '' check (char_length(title) <= 200),
  excerpt text not null default '' check (char_length(excerpt) <= 120),
  subject text not null default '' check (char_length(subject) <= 32),
  status text not null default '' check (char_length(status) <= 32),
  parent_kind text not null default '' check (char_length(parent_kind) <= 32),
  parent_local_id text not null default '' check (char_length(parent_local_id) <= 100),
  relations jsonb not null default '{}'::jsonb,
  local_available boolean not null default false,
  source_updated_at timestamptz,
  content_sha256 text check (content_sha256 is null or length(content_sha256) = 64),
  metadata_sha256 text not null check (length(metadata_sha256) = 64),
  sync_run uuid not null,
  indexed_at timestamptz not null default now(),
  primary key (user_id, device_id, kind, local_id),
  foreign key (user_id, device_id)
    references public.learning_inventory (user_id, device_id) on delete cascade
);

create index learning_catalog_user_kind_idx
  on public.learning_catalog (user_id, kind, source_updated_at desc);

alter table public.learning_inventory enable row level security;
alter table public.learning_catalog enable row level security;
revoke all on public.learning_inventory from anon;
revoke all on public.learning_catalog from anon;
grant select, insert, update, delete on public.learning_inventory to authenticated;
grant select, insert, update, delete on public.learning_catalog to authenticated;

create policy "Owners manage their inventory" on public.learning_inventory
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Owners manage their catalog" on public.learning_catalog
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- Discarding an unfinished question is account-wide. A formal intake of the
-- same ID takes priority; an offline device still cannot republish an old draft.
create table public.learning_tombstones (
  user_id uuid not null references auth.users (id) on delete cascade,
  kind text not null check (kind = 'question'),
  local_id text not null check (length(local_id) between 1 and 100),
  deleted_at timestamptz not null,
  origin_device_id uuid not null,
  superseded_at timestamptz,
  primary key (user_id, kind, local_id)
);
alter table public.learning_tombstones enable row level security;
revoke all on public.learning_tombstones from anon;
grant select, insert on public.learning_tombstones to authenticated;
grant update (superseded_at) on public.learning_tombstones to authenticated;
create policy "Owners read their tombstones" on public.learning_tombstones
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "Owners insert their tombstones" on public.learning_tombstones
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Owners resolve their tombstones" on public.learning_tombstones
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create function public.reject_tombstoned_catalog_item()
returns trigger language plpgsql set search_path = '' as $$
begin
  if exists (select 1 from public.learning_tombstones t
             where t.user_id = new.user_id and t.kind = new.kind
               and t.local_id = new.local_id) then
    if new.kind = 'question' and new.status not in ('draft', 'deleted') then
      -- A formal intake takes priority over a stale draft deletion.
      update public.learning_tombstones t set superseded_at = now()
        where t.user_id = new.user_id and t.kind = new.kind
          and t.local_id = new.local_id and t.superseded_at is null;
    else
      raise exception 'This draft was discarded on another device';
    end if;
  end if;
  return new;
end;
$$;
create trigger reject_tombstoned_catalog_item
  before insert or update on public.learning_catalog
  for each row execute function public.reject_tombstoned_catalog_item();

create function public.remove_tombstoned_catalog_items()
returns trigger language plpgsql set search_path = '' as $$
begin
  delete from public.learning_catalog c
    where c.user_id = new.user_id and c.kind = new.kind
      and c.local_id = new.local_id and c.status in ('draft', 'deleted');
  if exists (select 1 from public.learning_catalog c
             where c.user_id = new.user_id and c.kind = new.kind
               and c.local_id = new.local_id
               and c.status not in ('draft', 'deleted')) then
    update public.learning_tombstones t set superseded_at = now()
      where t.user_id = new.user_id and t.kind = new.kind
        and t.local_id = new.local_id;
  end if;
  return new;
end;
$$;
create trigger remove_tombstoned_catalog_items
  after insert on public.learning_tombstones
  for each row execute function public.remove_tombstoned_catalog_items();

-- A private, short-lived relay for device-to-device payloads. The receiving
-- device must verify and acknowledge bytes before a source copy is removable.
create table public.learning_transfer_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  kind text not null check (kind in ('question', 'knowledge', 'node', 'asset')),
  local_id text not null check (length(local_id) between 1 and 100),
  source_device_id uuid not null,
  target_device_id uuid not null check (target_device_id <> source_device_id),
  expected_sha256 text check (expected_sha256 is null or length(expected_sha256) = 64),
  status text not null default 'requested'
    check (status in ('requested', 'ready', 'received', 'failed')),
  chunk_count integer not null default 0 check (chunk_count between 0 and 1000),
  byte_size bigint not null default 0 check (byte_size between 0 and 1073741824),
  package_sha256 text check (package_sha256 is null or length(package_sha256) = 64),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index learning_transfer_pending_idx
  on public.learning_transfer_requests (user_id, status, source_device_id, target_device_id);
alter table public.learning_transfer_requests enable row level security;
revoke all on public.learning_transfer_requests from anon;
grant select, insert, update, delete on public.learning_transfer_requests to authenticated;
create policy "Owners manage their transfer requests" on public.learning_transfer_requests
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('learning-relay', 'learning-relay', false, 5242880,
        array['application/octet-stream'])
on conflict (id) do nothing;

create policy "Owners read relay objects" on storage.objects
  for select to authenticated
  using (bucket_id = 'learning-relay'
    and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "Owners upload relay objects" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'learning-relay'
    and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "Owners clean relay objects" on storage.objects
  for delete to authenticated
  using (bucket_id = 'learning-relay'
    and (storage.foldername(name))[1] = (select auth.uid())::text);
