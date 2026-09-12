-- ============================================================================
-- Handseller Bookkeeping — Supabase PostgreSQL schema
-- Run this once against a fresh Supabase project (SQL Editor or `supabase db`).
-- ============================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table if not exists users (
    id          uuid primary key default gen_random_uuid(),
    email       text not null unique,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- orgs
-- ---------------------------------------------------------------------------
create table if not exists orgs (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    owner_id    uuid not null references users(id) on delete restrict,
    created_at  timestamptz not null default now()
);
create index if not exists idx_orgs_owner_id on orgs(owner_id);

-- ---------------------------------------------------------------------------
-- org_members — join table used by get_ownership() to verify membership.
-- (Owner is implicitly a member; additional members can be added here.)
-- ---------------------------------------------------------------------------
create table if not exists org_members (
    org_id      uuid not null references orgs(id) on delete cascade,
    user_id     uuid not null references users(id) on delete cascade,
    role        text not null default 'member',
    created_at  timestamptz not null default now(),
    primary key (org_id, user_id)
);
create index if not exists idx_org_members_user_id on org_members(user_id);

-- ---------------------------------------------------------------------------
-- sales
-- ---------------------------------------------------------------------------
create table if not exists sales (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    user_id             uuid not null references users(id) on delete restrict,
    amount              numeric(12, 2) not null check (amount >= 0),
    voucher_reference   text,
    sale_date           date not null,
    created_at          timestamptz not null default now()
);
create index if not exists idx_sales_org_id on sales(org_id);
create index if not exists idx_sales_org_id_id on sales(org_id, id);
create index if not exists idx_sales_org_id_sale_date on sales(org_id, sale_date);
create index if not exists idx_sales_user_id on sales(user_id);

-- ---------------------------------------------------------------------------
-- expenses
-- ---------------------------------------------------------------------------
create table if not exists expenses (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references orgs(id) on delete cascade,
    user_id         uuid not null references users(id) on delete restrict,
    amount          numeric(12, 2) not null check (amount >= 0),
    category        text not null,
    description     text,
    expense_date    date not null,
    created_at      timestamptz not null default now()
);
create index if not exists idx_expenses_org_id on expenses(org_id);
create index if not exists idx_expenses_org_id_id on expenses(org_id, id);
create index if not exists idx_expenses_org_id_expense_date on expenses(org_id, expense_date);
create index if not exists idx_expenses_org_id_category on expenses(org_id, category);
create index if not exists idx_expenses_user_id on expenses(user_id);

-- ---------------------------------------------------------------------------
-- idempotency_keys
-- ---------------------------------------------------------------------------
create table if not exists idempotency_keys (
    key             text primary key,
    user_id         uuid not null references users(id) on delete cascade,
    response_body   jsonb,
    status_code     integer,
    created_at      timestamptz not null default now()
);
create index if not exists idx_idempotency_keys_user_id on idempotency_keys(user_id);

-- ---------------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------------
create table if not exists agents (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    description     text,
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- agent_logs
-- ---------------------------------------------------------------------------
create table if not exists agent_logs (
    id                  uuid primary key default gen_random_uuid(),
    agent_id            uuid not null references agents(id) on delete cascade,
    org_id              uuid not null references orgs(id) on delete cascade,
    user_id             uuid not null references users(id) on delete restrict,
    action_summary      text not null,
    insights_generated  jsonb,
    executed_at         timestamptz not null default now()
);
create index if not exists idx_agent_logs_org_id on agent_logs(org_id);
create index if not exists idx_agent_logs_agent_id on agent_logs(agent_id);
create index if not exists idx_agent_logs_org_id_executed_at on agent_logs(org_id, executed_at);

-- ---------------------------------------------------------------------------
-- Seed the default financial advisor agent definition (idempotent)
-- ---------------------------------------------------------------------------
insert into agents (id, name, description)
select gen_random_uuid(), 'financial-advisor', 'Autonomous financial advisor that analyzes expenses/sales and proposes cost + pricing actions.'
where not exists (select 1 from agents where name = 'financial-advisor');
