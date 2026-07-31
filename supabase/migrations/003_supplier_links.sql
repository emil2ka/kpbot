-- Supplier links from Chinese marketplaces, optionally tied to a scanned Kaspi item.
create table if not exists public.supplier_links (
    id bigint generated always as identity primary key,
    scan_id uuid references public.kaspi_scans(id) on delete cascade,
    platform text not null,
    raw_url text not null,
    canonical_url text not null,
    item_id text,
    unit_price_cny numeric(10, 2),
    minimum_order_quantity integer default 1,
    weight_kg numeric(6, 3),
    notes text,
    created_at timestamptz not null default now()
);

create index if not exists supplier_links_scan_id_idx on public.supplier_links (scan_id);

alter table public.supplier_links enable row level security;
