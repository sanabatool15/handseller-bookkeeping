# Handseller Bookkeeping Backend

Internal bookkeeping backend for handseller sales and expense tracking, built
with FastAPI and Supabase.

## Architecture

Strict separation of concerns, enforced by directory:

```
app/
  routers/      FastAPI endpoints only. Parse/validate the request, call a
                service function, return its result. No business logic,
                no database access.
  services/     All business logic and calculations (e.g. monthly report
                totals). Delegates every database read/write to the
                repository layer. Also enforces authorization decisions
                (404 vs 403) based on data returned by the repository.
  repository/   The ONLY layer allowed to talk to Supabase. Every query
                here is filtered by org_id to enforce tenant isolation.
  models/       Pydantic schemas for sales, expenses, and reports.
  auth.py       get_current_user dependency: decodes the JWT and extracts
                user_id/org_id.
  db.py         Supabase client lifecycle (created on startup).
  config.py     Environment-based settings.
  main.py       FastAPI app wiring: routers, CORS, startup/shutdown.

sql/
  schema.sql    Table definitions for `sales` and `expenses`, indexes, and
                Postgres RLS policies as defense-in-depth.
```

Request flow: `router -> service -> repository -> Supabase`. A router never
imports from `repository`; a service never imports the Supabase client
directly.

## Data model

Every `sales` and `expenses` row carries `org_id` and `user_id`. All
repository queries filter `.eq("org_id", ...)` against the caller's
authenticated org, so one tenant can never read or write another tenant's
rows through the API. Postgres Row Level Security policies in
`sql/schema.sql` provide a second layer of protection.

## Security model

* `app/auth.get_current_user` is a FastAPI dependency that decodes the
  bearer JWT (HS256 by default) and returns a `CurrentUser(user_id, org_id)`.
* Every router endpoint depends on `get_current_user` and passes the result
  down to its service function.
* Services fetch a record by id (no org filter), then compare its `org_id`
  against `current.org_id`:
  * record missing -> `404 Not Found`
  * record belongs to a different org -> `403 Forbidden`
  * otherwise the operation proceeds, and mutations are additionally scoped
    by org_id at the repository layer as a second guard.

## Endpoints

* `POST   /sales` - log a sale
* `GET    /sales?start=&end=` - list sales (optionally by date range)
* `GET    /sales/{sale_id}` - fetch one sale
* `PATCH  /sales/{sale_id}` - update a sale
* `DELETE /sales/{sale_id}` - delete a sale
* `POST   /expenses` - log an expense
* `GET    /expenses?start=&end=` - list expenses (optionally by date range)
* `GET    /expenses/{expense_id}` - fetch one expense
* `PATCH  /expenses/{expense_id}` - update an expense
* `DELETE /expenses/{expense_id}` - delete an expense
* `GET    /reports/monthly?year=&month=` - total sales, total expenses, and
  net profit/loss for the given month
* `GET    /health` - liveness check

## Running locally

```bash
cp .env.example .env
# fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, JWT_SECRET

pip install -e .
uvicorn app.main:app --reload
```

Apply `sql/schema.sql` to your Supabase project (SQL editor or `psql`)
before starting the API.

Authenticate requests with `Authorization: Bearer <jwt>`, where the JWT is
signed with `JWT_SECRET` and includes `user_id` (or `sub`) and `org_id`
claims.
