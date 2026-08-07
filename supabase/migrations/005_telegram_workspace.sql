-- Personal sourcing workspace used by the Telegram experience.
create table if not exists public.telegram_profiles (
  telegram_id bigint primary key,
  city text,
  test_budget_kzt numeric,
  target_margin_percent numeric not null default 35,
  excluded_categories text[] not null default '{}',
  goal text,
  onboarded boolean not null default false,
  updated_at timestamptz not null default now()
);

alter table public.telegram_profiles enable row level security;
