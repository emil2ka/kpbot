-- Historical evidence for trend reports. Apply in the Supabase SQL editor.
create table if not exists public.trend_watches (
  id uuid primary key default gen_random_uuid(),
  kaspi_url text not null unique,
  title text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.kaspi_trend_snapshots (
  id bigint generated always as identity primary key,
  watch_id uuid not null references public.trend_watches(id) on delete cascade,
  observed_at timestamptz not null default now(),
  price_kzt integer,
  review_count integer,
  seller_count integer,
  rating numeric,
  unique (watch_id, observed_at)
);

create table if not exists public.youtube_trend_snapshots (
  id bigint generated always as identity primary key,
  query text not null,
  observed_at timestamptz not null default now(),
  video_count_30d integer not null,
  video_count_7d integer not null,
  total_views integer not null,
  median_views_per_day numeric,
  source_note text not null
);

create index if not exists kaspi_trend_snapshots_watch_time_idx on public.kaspi_trend_snapshots (watch_id, observed_at desc);
create index if not exists youtube_trend_snapshots_query_time_idx on public.youtube_trend_snapshots (query, observed_at desc);

alter table public.trend_watches enable row level security;
alter table public.kaspi_trend_snapshots enable row level security;
alter table public.youtube_trend_snapshots enable row level security;
