-- Handseller Bookkeeping schema
-- Every record is scoped to an org (tenant) and the user who created it.

create extension if not exists "pgcrypto";

create table if not exists sales (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null,
    user_id uuid not null,
    sale_date date not null,
    description text not null,
    amount numeric(12, 2) not null check (amount >= 0),
    quantity integer not null default 1 check (quantity > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists expenses (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null,
    user_id uuid not null,
    expense_date date not null,
    description text not null,
    amount numeric(12, 2) not null check (amount >= 0),
    category text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_sales_org_id on sales (org_id);
create index if not exists idx_sales_org_date on sales (org_id, sale_date);
create index if not exists idx_expenses_org_id on expenses (org_id);
create index if not exists idx_expenses_org_date on expenses (org_id, expense_date);

-- Row Level Security: defense in depth. The application also enforces
-- tenant isolation at the repository layer (see app/repository/*), but
-- RLS ensures a leaked service key / misconfigured client cannot cross
-- tenant boundaries when using Supabase's PostgREST access directly.

alter table sales enable row level security;
alter table expenses enable row level security;

-- These policies assume the JWT's custom claim "org_id" is available via
-- auth.jwt() ->> 'org_id' when Supabase Auth JWTs are used directly. If a
-- separate auth system issues JWTs and the backend calls Supabase with the
-- service role key, RLS is bypassed by design and isolation is enforced
-- entirely in the repository layer.

create policy sales_tenant_isolation on sales
    using (org_id = (auth.jwt() ->> 'org_id')::uuid)
    with check (org_id = (auth.jwt() ->> 'org_id')::uuid);

create policy expenses_tenant_isolation on expenses
    using (org_id = (auth.jwt() ->> 'org_id')::uuid)
    with check (org_id = (auth.jwt() ->> 'org_id')::uuid);

create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger sales_set_updated_at
    before update on sales
    for each row execute function set_updated_at();

create trigger expenses_set_updated_at
    before update on expenses
    for each row execute function set_updated_at();
