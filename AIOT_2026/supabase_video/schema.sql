-- Private service-only metadata. Video bytes live in the private Storage bucket.
create table public.breathing_video_devices (
  camera_id text primary key check (camera_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  upload_key_hash text not null check (upload_key_hash ~ '^[0-9a-f]{64}$'),
  read_key_hash text not null check (read_key_hash ~ '^[0-9a-f]{64}$'),
  active_session uuid,
  active_capture_start timestamptz
);
create table public.breathing_video_settings (
  key text primary key, value text not null
);
create table public.breathing_video_segments (
  camera_id text not null references public.breathing_video_devices(camera_id),
  session_id uuid not null,
  sequence bigint not null check (sequence >= 0),
  object_path text not null unique,
  capture_start timestamptz not null,
  capture_end timestamptz not null,
  expires_at timestamptz not null,
  fps integer not null default 10 check (fps = 10),
  frame_count integer not null default 20 check (frame_count = 20),
  created_at timestamptz not null default now(),
  primary key (camera_id, session_id, sequence),
  check (capture_end = capture_start + interval '2 seconds'),
  check (expires_at = capture_start + interval '3 minutes')
);
create index breathing_video_segments_latest_idx
  on public.breathing_video_segments(camera_id, session_id, capture_end desc);
create index breathing_video_segments_expiry_idx
  on public.breathing_video_segments(expires_at);

alter table public.breathing_video_devices enable row level security;
alter table public.breathing_video_settings enable row level security;
alter table public.breathing_video_segments enable row level security;

-- Storage commits the object atomically. Reserved-but-unuploaded rows are not ready.
create view public.breathing_video_ready with (security_invoker = true) as
select s.*, o.created_at as uploaded_at, o.metadata ->> 'eTag' as etag
from public.breathing_video_segments s
join storage.objects o on o.bucket_id = 'breathing-video' and o.name = s.object_path
where s.expires_at > now();

-- Read Storage metadata only; the Edge Function removes actual objects through its API.
create view public.breathing_video_expired_objects with (security_invoker = true) as
select o.name as object_path
from storage.objects o
left join public.breathing_video_segments s on s.object_path = o.name
where o.bucket_id = 'breathing-video'
  and (s.object_path is null or s.expires_at <= now());

revoke all on public.breathing_video_devices, public.breathing_video_settings,
  public.breathing_video_segments, public.breathing_video_ready,
  public.breathing_video_expired_objects from public, anon, authenticated;
grant select, insert, update, delete on public.breathing_video_devices,
  public.breathing_video_settings, public.breathing_video_segments to service_role;
grant select on public.breathing_video_ready, public.breathing_video_expired_objects to service_role;

create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

do $$
declare cleanup_secret text := encode(gen_random_bytes(32), 'hex');
begin
  perform vault.create_secret(cleanup_secret, 'breathing_video_cleanup_key', 'Private video retention worker');
  insert into public.breathing_video_settings(key, value)
  values ('cleanup_key_hash', encode(sha256(convert_to(cleanup_secret, 'UTF8')), 'hex'));
end $$;
