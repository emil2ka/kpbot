-- Upgrade databases created before profile onboarding fields were persisted.
alter table public.telegram_profiles
  add column if not exists goal text,
  add column if not exists onboarded boolean not null default false;
