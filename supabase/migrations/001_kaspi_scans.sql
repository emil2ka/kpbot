create table if not exists public.kaspi_scans (
  id uuid primary key default gen_random_uuid(),
  source_url text not null,
  title text not null,
  price_kzt integer,
  review_count integer,
  seller_count integer,
  rating numeric,
  image_url text,
  scraped_at timestamptz not null,
  passes_hard_filters boolean not null,
  filter_reasons jsonb not null default '[]'::jsonb,
  ai_assessment jsonb,
  created_at timestamptz not null default now()
);

create index if not exists kaspi_scans_scraped_at_idx on public.kaspi_scans (scraped_at desc);

alter table public.kaspi_scans enable row level security;

