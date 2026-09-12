-- Handseller Bookkeeping — Supabase PostgreSQL Schema
-- Run this in the Supabase SQL editor (or via `supabase db push`).

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- Mirrors (or extends) Supabase's auth.users. Kept as an explicit app-level
-- table so ownership checks and foreign keys stay simple and explicit.
-- ---------------------------------------------------------------------------
create table if not exists public.users (
    id          uuid primary key default gen_random_uuid(),
    email       text not null unique,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- orgs
-- A business/organization owned by a single user (the handseller / owner).
-- ---------------------------------------------------------------------------
create table if not exists public.orgs (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    owner_id    uuid not null references public.users(id) on delete cascade,
    created_at  timestamptz not null default now()
);

create index if not exists idx_orgs_owner_id on public.orgs(owner_id);

-- ---------------------------------------------------------------------------
-- sales
-- Daily sales log. voucher_reference stores a text/URL pointer to the
-- voucher/receipt evidencing the sale.
-- ---------------------------------------------------------------------------
create table if not exists public.sales (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references public.orgs(id) on delete cascade,
    amount              numeric(12, 2) not null check (amount >= 0),
    voucher_reference   text,
    sale_date           date not null default current_date,
    created_at          timestamptz not null default now()
);

create index if not exists idx_sales_org_id on public.sales(org_id);
create index if not exists idx_sales_org_id_sale_date on public.sales(org_id, sale_date);

-- ---------------------------------------------------------------------------
-- expenses
-- Daily expenses log, grouped by category for analytics.
-- ---------------------------------------------------------------------------
create table if not exists public.expenses (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references public.orgs(id) on delete cascade,
    amount          numeric(12, 2) not null check (amount >= 0),
    category        text not null,
    expense_date    date not null default current_date,
    created_at      timestamptz not null default now()
);

create index if not exists idx_expenses_org_id on public.expenses(org_id);
create index if not exists idx_expenses_org_id_expense_date on public.expenses(org_id, expense_date);
create index if not exists idx_expenses_org_id_category on public.expenses(org_id, category);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- The API layer performs its own explicit ownership checks (see
-- repository/ownership_repo.py), but RLS is enabled here as defense in depth
-- for direct DB access. Adjust policies to match your auth setup.
-- ---------------------------------------------------------------------------
alter table public.users    enable row level security;
alter table public.orgs     enable row level security;
alter table public.sales    enable row level security;
alter table public.expenses enable row level security;

-- Users can read their own row.
create policy if not exists users_select_self on public.users
    for select using (id = auth.uid());

-- Owners can see/manage orgs they own.
create policy if not exists orgs_owner_all on public.orgs
    for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Sales/expenses are only visible/writable for orgs the requester owns.
create policy if not exists sales_owner_all on public.sales
    for all using (
        exists (select 1 from public.orgs o where o.id = sales.org_id and o.owner_id = auth.uid())
    ) with check (
        exists (select 1 from public.orgs o where o.id = sales.org_id and o.owner_id = auth.uid())
    );

create policy if not exists expenses_owner_all on public.expenses
    for all using (
        exists (select 1 from public.orgs o where o.id = expenses.org_id and o.owner_id = auth.uid())
    ) with check (
        exists (select 1 from public.orgs o where o.id = expenses.org_id and o.owner_id = auth.uid())
    );
