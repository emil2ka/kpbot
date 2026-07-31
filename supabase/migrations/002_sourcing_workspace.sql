create table if not exists public.sourcing_items (
  id uuid primary key default gen_random_uuid(),
  owner_telegram_id bigint,
  title text not null,
  kaspi_url text,
  image_url text,
  status text not null default 'idea' check (status in ('idea', 'researching', 'sample', 'ordered', 'in_transit', 'selling', 'rejected')),
  potential_score integer check (potential_score between 0 and 100),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.supplier_offers (
  id uuid primary key default gen_random_uuid(),
  sourcing_item_id uuid not null references public.sourcing_items(id) on delete cascade,
  platform text not null,
  source_url text not null,
  unit_price_cny numeric,
  minimum_order_quantity integer,
  weight_kg numeric,
  notes text,
  created_at timestamptz not null default now()
);

create index if not exists sourcing_items_owner_status_idx on public.sourcing_items (owner_telegram_id, status);
create index if not exists supplier_offers_item_idx on public.supplier_offers (sourcing_item_id);

alter table public.sourcing_items enable row level security;
alter table public.supplier_offers enable row level security;
