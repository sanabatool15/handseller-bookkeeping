-- Handseller bookkeeping schema for Supabase (PostgreSQL).
-- Run this in the Supabase SQL editor (or via the Supabase CLI) before using the API.

create extension if not exists "pgcrypto";

create table if not exists sellers (
    id uuid primary key default gen_random_uuid(),
    full_name text not null,
    email text,
    phone text,
    commission_rate numeric not null default 0,
    is_active boolean not null default true,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists customers (
    id uuid primary key default gen_random_uuid(),
    full_name text not null,
    email text,
    phone text,
    address text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists products (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    sku text,
    description text,
    unit_price numeric not null default 0,
    unit_cost numeric not null default 0,
    quantity_on_hand integer not null default 0,
    reorder_level integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists sales (
    id uuid primary key default gen_random_uuid(),
    seller_id uuid not null references sellers(id),
    customer_id uuid references customers(id),
    sale_date date not null,
    items jsonb not null default '[]', -- [{product_id, quantity, unit_price}, ...]
    total_amount numeric not null default 0,
    status text not null default 'completed',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists invoices (
    id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references customers(id),
    sale_id uuid references sales(id),
    invoice_number text not null unique,
    issue_date date not null,
    due_date date,
    amount_due numeric not null default 0,
    status text not null default 'unpaid',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists payments (
    id uuid primary key default gen_random_uuid(),
    sale_id uuid references sales(id),
    invoice_id uuid references invoices(id),
    customer_id uuid references customers(id),
    amount numeric not null,
    payment_date date not null,
    method text not null default 'cash',
    reference text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists expenses (
    id uuid primary key default gen_random_uuid(),
    seller_id uuid references sellers(id),
    category text not null,
    amount numeric not null,
    expense_date date not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Keep updated_at fresh on every update.
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$
declare
  t text;
begin
  foreach t in array array['sellers','customers','products','sales','invoices','payments','expenses']
  loop
    execute format('drop trigger if exists set_updated_at on %I;', t);
    execute format('create trigger set_updated_at before update on %I for each row execute function set_updated_at();', t);
  end loop;
end $$;

-- Enable Row Level Security. Add policies appropriate to your auth model
-- (e.g. allow the service_role key full access, or scope by an owner/tenant column).
alter table sellers enable row level security;
alter table customers enable row level security;
alter table products enable row level security;
alter table sales enable row level security;
alter table invoices enable row level security;
alter table payments enable row level security;
alter table expenses enable row level security;
