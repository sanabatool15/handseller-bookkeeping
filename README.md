# Handseller Bookkeeping API

A FastAPI + Supabase backend for handseller bookkeeping: daily sales/expense
tracking, monthly financial reports, and expense analytics — with strict
per-org ownership checks on every request.

## Architecture

Strict separation of concerns, enforced by directory:

```
app/
  routers/       FastAPI endpoints only. No business logic, no DB calls.
                 Extract path/query params + the authenticated user, call a
                 service function, return its result.
  services/      Business logic, validation, and analytics. No direct DB
                 calls — delegates all persistence to repository/. Every
                 operation calls ownership_service.assert_owns_org() (which
                 wraps repository.ownership_repo.get_ownership()) before any
                 read/write on org-scoped data.
  repository/    The ONLY layer allowed to execute Supabase queries. Thin,
                 dumb data-access functions — no business logic.
  models/        Pydantic request/response schemas (validation lives here).
  core/          Config, JWT auth dependency (get_current_user), and the
                 AppError exception hierarchy -> HTTP status mapping.
  db/            Supabase client construction/lifecycle (app/db/client.py).
                 Only repository/ imports from here.
  main.py        Wires routers, CORS, startup/shutdown, exception handlers.
```

Request flow: `router -> service -> repository -> Supabase`. Nothing skips a
layer; e.g. routers never import `repository/` or `db/` directly.

## Security model

- `get_current_user` (in `app/core/security.py`) is a FastAPI dependency that
  decodes the `Authorization: Bearer <jwt>` header (a Supabase-issued JWT,
  HS256 signed with `SUPABASE_JWT_SECRET`) and returns the authenticated
  `user_id` (the token's `sub` claim). This is the *only* source of identity
  used anywhere in the app.
- `org_id` is **never** trusted from a request body or query string for
  authorization purposes — it is only used as a lookup key, and every service
  function calls `assert_owns_org(user_id, org_id)` (which calls
  `repository.ownership_repo.get_ownership(user_id, org_id)`, a direct query
  against `orgs.owner_id`) before doing anything else. A failed check raises
  `ForbiddenError` -> HTTP 403 with a message naming the user and org.
- Supabase Row Level Security policies (in `supabase/schema.sql`) provide a
  second layer of defense in case of direct DB access outside the API.

## Error handling

Domain errors are raised as typed exceptions (`app/core/exceptions.py`) and
translated into HTTP responses by a single handler in `app/main.py`:

| Exception            | HTTP status | Example detail message                                   |
|-----------------------|-------------|------------------------------------------------------------|
| `ValidationAppError` | 422         | "Invalid 'month' value [2025-13]. Expected format YYYY-MM." |
| `ForbiddenError`     | 403         | "User [abc-123] does not own org_id [xyz-789]."             |
| `NotFoundError`      | 404         | "Org [xyz-789] was not found."                              |

Pydantic model validation failures (missing/invalid fields in a request body)
are caught by FastAPI automatically and re-formatted by a
`RequestValidationError` handler into explicit per-field messages, e.g.
`"Field 'amount': Input should be greater than 0"`, with HTTP 422.

## Database schema (Supabase / PostgreSQL)

See `supabase/schema.sql` for the full DDL. Summary:

- `users(id, email, created_at)`
- `orgs(id, name, owner_id -> users.id)`
- `sales(id, org_id -> orgs.id, amount, voucher_reference, sale_date)`
- `expenses(id, org_id -> orgs.id, amount, category, expense_date)`

Run the SQL in the Supabase SQL editor (or via the CLI: `supabase db push`)
against your project.

## Endpoints

All endpoints require `Authorization: Bearer <jwt>`.

- `POST   /orgs` — create an org owned by the authenticated user.
- `GET    /orgs` — list orgs owned by the authenticated user.
- `GET    /orgs/{org_id}` — get one org (403 if not owned).
- `POST   /orgs/{org_id}/sales` — log a sale (`amount`, optional `voucher_reference`, optional `sale_date`).
- `GET    /orgs/{org_id}/sales?start_date=&end_date=` — list sales.
- `POST   /orgs/{org_id}/expenses` — log an expense (`amount`, `category`, optional `expense_date`).
- `GET    /orgs/{org_id}/expenses?start_date=&end_date=` — list expenses.
- `GET    /orgs/{org_id}/reports/monthly?month=YYYY-MM` — total sales, total expenses, net profit/loss for that month.
- `GET    /orgs/{org_id}/reports/expense-analytics?start_date=&end_date=` — expenses grouped/aggregated by category, sorted by spend, with `top_category` and per-category percentage of total.
- `GET    /health` — liveness check.

## Running locally

```bash
# 1. Install dependencies (uses pyproject.toml)
pip install -e .

# 2. Configure environment
cp .env.example .env
# then fill in SUPABASE_URL, SUPABASE_KEY, SUPABASE_JWT_SECRET

# 3. Apply the schema to your Supabase project
#    (paste supabase/schema.sql into the Supabase SQL editor, or use the CLI)

# 4. Run the API
uvicorn app.main:app --reload
```

The interactive API docs are then available at `http://localhost:8000/docs`.

## Notes / assumptions

- Auth: this project assumes JWTs are issued by Supabase Auth (HS256, signed
  with the project's JWT secret, `sub` claim = user id). Swap the verification
  in `app/core/security.py` for RS256/JWKS if you switch to asymmetric Supabase
  JWTs.
- The `users` table mirrors `auth.users` at the app level so `orgs.owner_id`
  has an explicit FK target; sync it via a Supabase trigger or on first login
  in a real deployment.
- Monetary amounts are validated as positive `Decimal`s in Pydantic models and
  stored as PostgreSQL `numeric(12,2)`.
