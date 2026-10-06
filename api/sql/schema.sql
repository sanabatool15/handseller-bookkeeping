-- Handseller Bookkeeping: Supabase (PostgreSQL) schema
-- Apply via the Supabase SQL editor or `supabase db push`.

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------------
-- updated_at trigger helper
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------------
-- orgs
-- ---------------------------------------------------------------------------
create table if not exists orgs (
    id uuid primary key default uuid_generate_v4(),
    name text not null,
    owner_id uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create trigger trg_orgs_updated_at
    before update on orgs
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table if not exists users (
    id uuid primary key default uuid_generate_v4(),
    org_id uuid references orgs(id) on delete cascade,
    email text unique not null,
    full_name text,
    hashed_password text not null,
    role text not null default 'member', -- owner | admin | member
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create trigger trg_users_updated_at
    before update on users
    for each row execute function set_updated_at();

alter table orgs
    add constraint fk_orgs_owner foreign key (owner_id) references users(id) deferrable initially deferred;

-- ---------------------------------------------------------------------------
-- sales
-- ---------------------------------------------------------------------------
create table if not exists sales (
    id uuid primary key default uuid_generate_v4(),
    org_id uuid not null references orgs(id) on delete cascade,
    created_by uuid references users(id),
    amount numeric(14, 2) not null,
    category text not null default 'general',
    description text,
    customer_name text,
    sale_date date not null default current_date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_sales_org_id on sales(org_id);

create trigger trg_sales_updated_at
    before update on sales
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- expenses
-- ---------------------------------------------------------------------------
create table if not exists expenses (
    id uuid primary key default uuid_generate_v4(),
    org_id uuid not null references orgs(id) on delete cascade,
    created_by uuid references users(id),
    amount numeric(14, 2) not null,
    category text not null default 'general',
    voucher_reference text,
    description text,
    expense_date date not null default current_date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_expenses_org_id on expenses(org_id);

create trigger trg_expenses_updated_at
    before update on expenses
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- agent_jobs
-- ---------------------------------------------------------------------------
create table if not exists agent_jobs (
    id uuid primary key default uuid_generate_v4(),
    job_name text not null,
    org_id uuid not null references orgs(id) on delete cascade,
    requested_by uuid references users(id),
    status text not null default 'pending', -- pending | processing | completed | failed
    current_step text,
    input_payload jsonb,
    result jsonb,
    error_details jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_agent_jobs_org_id on agent_jobs(org_id);

create trigger trg_agent_jobs_updated_at
    before update on agent_jobs
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- agent_logs
-- ---------------------------------------------------------------------------
create table if not exists agent_logs (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid not null references agent_jobs(id) on delete cascade,
    step_name text not null,
    action_summary text,
    insights_generated jsonb,
    executed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_agent_logs_job_id on agent_logs(job_id);

create trigger trg_agent_logs_updated_at
    before update on agent_logs
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security (defense in depth; the app layer also structurally
-- scopes every query by org_id, see repository/*.py)
-- ---------------------------------------------------------------------------
alter table sales enable row level security;
alter table expenses enable row level security;
alter table agent_jobs enable row level security;
alter table agent_logs enable row level security;

create policy sales_org_isolation on sales
    using (org_id = current_setting('app.current_org_id', true)::uuid);

create policy expenses_org_isolation on expenses
    using (org_id = current_setting('app.current_org_id', true)::uuid);

create policy agent_jobs_org_isolation on agent_jobs
    using (org_id = current_setting('app.current_org_id', true)::uuid);
