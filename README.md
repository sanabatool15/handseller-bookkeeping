# Handseller Bookkeeping API

A backend for tracking the bookkeeping of a handseller business: sellers, customers,
products/inventory, sales, payments, expenses, and invoices. Built with **FastAPI** and
**Supabase** (PostgreSQL) as the database.

## Stack

- Python 3.10+
- FastAPI + Uvicorn
- Supabase (via `supabase-py`) for the database
- Pydantic v2 models for request/response validation

## Project layout

```
app/
  main.py               # FastAPI app, CORS, router wiring, startup/shutdown
  core/
    config.py           # Settings loaded from environment (.env)
    supabase_client.py   # Supabase client init/close + FastAPI dependency
    crud.py              # Small shared CRUD helpers over supabase-py
  models/                # Pydantic domain models (one file per resource)
  routers/               # API routes, one router per resource
supabase/
  schema.sql             # SQL to create the tables in your Supabase project
pyproject.toml
.env.example
```

## Setup

### 1. Create a Supabase project

Create a project at https://supabase.com, then open the SQL editor and run
`supabase/schema.sql` to create the tables (sellers, customers, products, sales,
invoices, payments, expenses) with UUID primary keys and `updated_at` triggers.

### 2. Install dependencies

This project is configured via `pyproject.toml`. Using `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
# or, to also install dev/test tools:
pip install -e ".[dev]"
```

(Any PEP 517 compatible tool works too, e.g. `uv sync` or `poetry install` after
adapting the lock step to your tool of choice.)

### 3. Configure environment variables

```bash
cp .env.example .env
```

Then fill in `.env`:

- `SUPABASE_URL` — your Supabase project URL (Settings -> API).
- `SUPABASE_KEY` — your `service_role` key for full server-side access (keep this
  secret; never ship it to a browser/client). You can use the `anon` key instead
  if you enforce access purely through Row Level Security policies.
- `CORS_ORIGINS` — comma-separated list of origins allowed to call this API.
- `APP_ENV`, `APP_HOST`, `APP_PORT` — optional runtime configuration.

Never commit your real `.env` file — it's already in `.gitignore`.

### 4. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`, with interactive docs at
`http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

## API overview

All resource routers expose standard CRUD:

- `GET /{resource}` — list (supports `limit` / `offset` query params)
- `POST /{resource}` — create
- `GET /{resource}/{id}` — retrieve one
- `PATCH /{resource}/{id}` — partial update
- `DELETE /{resource}/{id}` — delete

Resources: `sellers`, `customers`, `products`, `sales`, `payments`, `expenses`,
`invoices`.

Additional endpoints:

- `POST /products/{id}/adjust-inventory` — increase/decrease stock on hand.
- `GET /reports/summary` — total revenue, expenses, and net profit over an
  optional date range (`start_date`, `end_date` query params).
- `GET /reports/sellers/{seller_id}/performance` — a seller's total sales and
  commission owed.
- `GET /health` — health check.

## Notes

- The Supabase client is created once on app startup (`lifespan` handler in
  `app/main.py`) and released on shutdown.
- `app/core/crud.py` centralizes simple `select` / `insert` / `update` / `delete`
  calls against Supabase's PostgREST-backed table API so each router stays small.
- Row Level Security is enabled on every table in `supabase/schema.sql` — add
  policies matching your auth model (e.g. allow `service_role` full access, or
  scope rows by an owner/tenant column) before using the `anon` key from a client.
