# Architecture: routers → services → repository

## What we did

Split the entire codebase into three strict layers, each with exactly one
responsibility, arranged as a one-directional call chain:

```
routers/     FastAPI route handlers ONLY
   ↓ calls
services/    business logic, validation, orchestration
   ↓ calls
repository/  the ONLY layer allowed to run db.table(...) Supabase queries
```

- `routers/*.py` (`auth_router.py`, `sales_router.py`, `expenses_router.py`,
  `agent_jobs_router.py`): parse the request, call exactly one service
  function, translate the result (or a raised exception) into an HTTP
  response. No `if`/`for` business logic, no direct database access.
- `services/*.py`: validate inputs beyond what Pydantic already checks,
  apply business rules (e.g. computing `net_profit_loss`), and are the only
  callers of `repository/`. A service never imports `app.clients.get_supabase`
  directly and never calls `.table(`.
- `repository/*.py`: the only files in the codebase (besides
  `mcp_gateway/server.py`'s read-only ledger path, which itself calls into
  `services/`) that call `db.table(...)`. Every repository function that
  reads, updates, or deletes a specific row is also responsible for
  enforcing the `id` + `org_id` scoping rule (see
  `03-multi-tenancy-security.md`).

`middleware/` sits outside this chain entirely (it wraps the whole request
before any router runs) and `jobs/`, `mcp_gateway/` reuse `services/` the same way
routers do, so validation/scoping logic is never duplicated per entry point.

## Why we did it

This is a direct fix for what went wrong in earlier variants of this same
project:

- **`variant-1`** put database calls, validation, and route handling in the
  same function — any change to the schema meant hunting through HTTP
  handler code to find the SQL.
- **`variant-2`** introduced the three folders, but a couple of routers
  still executed Supabase queries directly "just for this one endpoint,"
  and authorization checks were scattered between routers and services
  inconsistently.

Concentrating **all** database access in one layer means:

1. **The multi-tenancy rule can be audited in one place.** To verify no
   query leaks cross-tenant data, you only need to review `repository/*.py`
   — not every router and service in the app. `grep -rn "\.table(" .`
   should only ever return matches in `repository/` (and the read-only
   ledger helper in `services/financial_report_service.py`, which itself
   sits behind the same scoping rules).
2. **Business logic is testable without a database.** `services/*.py`
   functions take a Supabase client as a parameter, so unit tests
   (`tests/unit/`) pass in an in-memory fake and test the actual business
   logic (e.g. monthly profit/loss math) without touching a real database
   or even importing the real `supabase` client.
3. **Routers stay thin and boring.** A router's job is to be an adapter
   between HTTP and the service layer — this makes it trivial to expose the
   exact same logic through a second interface. This is exactly how
   `mcp_gateway/server.py`'s tools work: `log_sale`/`log_expense` call
   `services.sales_service` / `services.expenses_service` directly, the same
   functions the HTTP routers call, so a sale logged via REST and a sale
   logged via an MCP client go through identical validation and scoping.

## What would violate this (don't do these)

- A router calling `db.table(...)` directly "because it's a simple GET."
- A service importing `app.clients.get_supabase` and building its own query
  instead of calling a `repository/` function.
- A new feature's database access living in `services/` "temporarily" — if
  it needs to read/write the database, it belongs in `repository/`, full
  stop, even for a one-off script or a new one-endpoint feature.

## Enforcement

There is no runtime check that stops a violation — this is enforced by
convention and code review. If you are extending this codebase, the review
question to ask on every PR/diff is: *"Does this router or service call
`.table(` anywhere?"* If yes, move that call into `repository/`.
