# Handseller Bookkeeping Backend

A production-oriented backend for a handseller bookkeeping application:
FastAPI + Microsoft SQL Server (pyodbc; was Supabase/Postgres until slice F0b) + Redis + Inngest (resilient background jobs)
+ FastMCP (Model Context Protocol server over stdio) + the OpenAI Agents SDK,
with a rule-based offline fallback for AI-generated financial advice.

## Architecture

```
routers/       FastAPI route handlers ONLY (no business logic, no SQL)
services/      Business logic + validation (no direct DB access)
repository/    The ONLY layer allowed to run SQL (T-SQL via core/db.py `Db`)
middleware/    Auth (JWT) + Redis-backed Idempotency middleware
jobs/          Inngest client + the financial-advisor background function
mcp_gateway/   FastMCP server (stdio) — tools/resources/prompts/sampling/logging
               (renamed from mcp/ — see "Package-name collisions, fixed" below)
ai_agents/     (renamed from agents/ — see "Package-name collisions, fixed" below)
  prompts/     Agent + system prompts as .md files (never hardcoded strings)
  api/         OpenAI Agents SDK orchestration
  rules/       Deterministic rule-based fallback (works fully offline)
  tools/       Utility functions (web search, deep-link generation)
core/          FastAPI app wiring, settings, SQL Server (`db.py`, `clients.py`)/Redis clients, JWT
../sql_server/ T-SQL scripts 01_foundation.sql, 02_sales_expenses_agents.sql, 03_products.sql, 04_customers.sql, 05_sale_items_cash_recordsale.sql, 06_expenses_cash.sql (+ TEST_CASES.md)
sql/           LEGACY Postgres/Supabase schema, kept for reference only (no longer used)
tests/
  unit/        Mocked DB (in-memory fake) + fakeredis
  integration/ FastAPI TestClient against the same fakes
  e2e/         Full-stack workflow — skipped unless RUN_E2E=1 (see below)
```

### Strict layering

`routers/` never touches the database directly — it only calls into `services/`,
which validates input and calls `repository/`, the only place `db.query/query_one/execute`
is ever invoked. `tests/unit/test_repository_sql_rules.py` statically enforces the SQL rules
(literal SQL only, `id` always with `org_id`, no SQL outside `repository/`). Jobs and the MCP
server (which run outside FastAPI) get a connection from `core.clients.db_session()` and
still only call services/repositories.

> **Annotation (slice F0b):** earlier versions of this section described Supabase
> `db.table(...)` calls; Supabase has been removed from the backend entirely.

## Database schema

Run, in SSMS and in this order: `../sql_server/01_foundation.sql` (database `HandsellerDB`, `orgs`, `users`)
and `../sql_server/02_sales_expenses_agents.sql` (`sales`, `expenses`, `agent_jobs`, `agent_logs`). Both are
re-runnable. All tables have `created_at`/`updated_at` with an AFTER UPDATE trigger; there is **no Row Level
Security** (the application-layer `org_id` scoping below is the control). `agent_logs` carries its own `org_id`.
Manual checks: `../sql_server/TEST_CASES.md`. Details: `specs/13-sql-server-migration.md`.

> **Annotation:** `sql/schema.sql` is the old Supabase/Postgres schema (with RLS); it is no longer applied.

## Products & stock endpoints (slice F1, `../sql_server/03_products.sql`)

All require auth; `POST`/`PUT` require `Idempotency-Key`. Cross-tenant ids return 404. Details: `specs/14-inventory-and-cash-domain.md`.

| Endpoint | Notes |
|---|---|
| `POST /products` | 201. Body `name`, `sku`, `price` (>= 0), optional `stock_qty` (>= 0), `reorder_level` (>= 0). 422 invalid, 409 duplicate SKU in the org |
| `GET /products?limit=&offset=&low_stock=true` | ordered by name; `low_stock` = `stock_qty <= reorder_level` |
| `GET/PUT/DELETE /products/{id}` | PUT updates `name`, `sku`, `price`, `reorder_level`, `is_active` (never stock); 409 on SKU clash |
| `POST /products/{id}/adjust-stock` | body `{delta: int != 0, reason?: str}`; one atomic guarded `UPDATE`; 409 if stock would go negative, 404 unknown/other org |

## Sale line items, cash ledger and the atomic sale procedure (slice F3, `../sql_server/05_sale_items_cash_recordsale.sql`)

`POST /sales` now runs the stored procedure `usp_RecordSale`: sale + line items + stock decrement + cash balance + cash
ledger entry in ONE transaction (all or nothing). `DELETE /sales/{id}` runs `usp_VoidSale` (stock back, reversing cash entry).
Design, transaction boundaries and concurrency: `specs/14-inventory-and-cash-domain.md` (F3) and `specs/15-transactions-and-concurrency.md`.

| Endpoint | Behaviour |
|---|---|
| `POST /sales` | Body: `amount` (required only without items), optional `items: [{product_id, quantity > 0, unit_price? >= 0}]` (max 200; price defaults to the product's), `skip_invalid_items` (default false), `category`, `description`, `customer_name`, `customer_id`. With items the total is the sum of the lines and `amount` is ignored. 201 `committed`; 201 `partial` (body has `skipped_items: [{product_id, quantity, error_number, reason}]`); 409 `Not enough stock for <product>` and nothing changes; 404 `Product not found` (unknown or other org) / `Customer not found`; 422 validation |
| `GET /sales`, `GET/PUT /sales/{id}` | Sale JSON now has `customer_id` and `items` (list, `[]` for quick sales; each item has `product_name`, `unit_price`, `line_total`). `PUT` changes metadata; an `amount` change on a sale WITH items is 422, on a quick sale it posts an `adjustment` cash entry (F4) |
| `DELETE /sales/{id}` | 204: void in one transaction; 404 unknown/other org |
| `GET /cash/balance` | `{balance, updated_at}` (0.0 / null before the first posting) |
| `GET /cash/ledger?limit=&offset=` | newest first: `entry_type` (`sale`, `sale_void`, ...), signed `amount`, `balance_after`, `ref_type/ref_id`, `entry_date` (F4 adds filters, see below) |

## Expenses on the cash ledger, Cash endpoints (slice F4, `../sql_server/06_expenses_cash.sql`)

Run `05` (amended in F4) and then `06` in SSMS; both are re-runnable. Expenses now move cash exactly like sales: `usp_RecordExpense`,
`usp_VoidExpense` and `usp_AdjustEntryAmount` change the record, `cash_accounts.balance` and `cash_ledger` in ONE transaction. The cash balance MAY go negative
(spending before cashing up is allowed). Design: `specs/14-inventory-and-cash-domain.md` (F4) and `specs/15-transactions-and-concurrency.md` (section 7). All require auth; `POST`/`PUT` require `Idempotency-Key`; cross-tenant ids return 404.

| Endpoint | Behaviour |
|---|---|
| `POST /expenses` | Body `amount` (> 0, <= 999,999,999,999.99), `category` (<= 100), `voucher_reference` (<= 200), `description`. 201; the balance goes down by `amount` and an `expense` ledger entry (negative amount) is written; 422 invalid |
| `PUT /expenses/{id}` | Body any of `amount`, `category`, `voucher_reference`, `description`. A changed `amount` posts an `adjustment` entry (`-delta`: a higher expense lowers cash); other fields update in the same transaction; 404 unknown/other org |
| `DELETE /expenses/{id}` | 204: void in one transaction (`expense_void` entry gives the money back); 404 unknown/other org |
| `PUT /sales/{id}` with `amount` | quick sale: posts an `adjustment` entry (`+delta`); sale with items: 422 |
| `DELETE /products/{id}` | now **409** `Product has sales and cannot be deleted; deactivate it instead` when sale items reference it (use `PUT {"is_active": false}`) |
| `GET /cash/ledger?entry_type=&from=&to=&limit=&offset=` | optional filters: `entry_type` in `sale, sale_void, expense, expense_void, adjustment`; `from`/`to` = inclusive `entry_date` range (`YYYY-MM-DD`). 422 for an unknown type, a bad date or `from` > `to` |
| `GET /cash/summary?year=&month=` | default current UTC month: `{year, month, opening_balance, total_in, total_out, closing_balance, by_type}` (`total_out` positive magnitude, `by_type` net per type, all five types present). Computed in SQL (`SUM ... GROUP BY`) |

UI: new **Cash** page (`/cash`: balance, monthly summary cards, type/date filters, ledger with running balance); expenses and sales pages show API errors.

## Customers endpoints (slice F2, `../sql_server/04_customers.sql`)

All require auth; `POST`/`PUT` require `Idempotency-Key`. Cross-tenant ids return 404. Details: `specs/14-inventory-and-cash-domain.md`.

| Endpoint | Notes |
|---|---|
| `POST /customers` | 201. Body `name` (required, <= 200), optional `phone` (<= 32), `email`, `address`, `notes`. 422 invalid, 409 duplicate phone in the org (blank phone = none) |
| `GET /customers?limit=&offset=&q=` | ordered by name; `q` = prefix match on name or phone, wildcard characters are literal |
| `GET/PUT/DELETE /customers/{id}` | PUT: `name` never cleared; explicit `null` clears phone/email/address/notes. DELETE: 409 while the customer still has sales |
| `GET /customers/{id}/summary` | `{customer, total_sales, sale_count, last_sale_date}` computed in SQL (org-scoped on both tables) |
| `POST/PUT /sales` | accept optional `customer_id` (other org / unknown => 404 "Customer not found"); responses include `customer_id` (null when none); `PUT` with `customer_id: null` unlinks. Free-text `customer_name` still works |

## Structural multi-tenancy (critical)

Every read/update/delete in `repository/*.py` filters by **both** `id` and
`org_id` in the same database call, e.g.:

```python
db.query_one("SELECT TOP (1) * FROM sales WHERE id = ? AND org_id = ?", (sale_id, org_id))
```

There is no code path that fetches a record by id alone and separately
checks ownership afterward — the classic "check-then-fetch" IDOR bug is
structurally impossible here because the ownership filter and the fetch are
the same query. `repository/base.py` also exposes a generic
`get_ownership(db, table=..., record_id=..., org_id=...) -> bool` helper for
services that need a boolean ownership check without needing the full row.

This is regression-tested in `tests/unit/test_sales_service.py` and
`tests/integration/test_sales_multitenancy.py`: a sale created for org A
returns 404 (not 403 — its existence isn't even leaked) when org B requests,
updates, or deletes it by the same id.

## Idempotency (Redis)

`middleware/idempotency.py` requires an `Idempotency-Key` header on every
`POST`/`PUT`/`PATCH`. On first use, the request runs and its status code +
JSON body are cached in Redis (`idempotency:{org_id}:{key}`, 24h TTL by
default via `IDEMPOTENCY_TTL_SECONDS`). A repeat request with the same key
(scoped per-org) returns the cached response immediately without re-running
the handler or hitting the DB again. A short `SET NX` lock also returns 409
if two requests with the same key race concurrently.

## Resilient background jobs (Inngest)

`POST /agent-jobs/financial-advice` **never** runs the agent synchronously.
It creates an `agent_jobs` row (status `pending`) and fires a
`financial/advice.requested` event to Inngest, returning `202 Accepted` with
the `job_id` immediately. `GET /agent-jobs/{job_id}` polls status.

`jobs/financial_agent_job.py` defines the actual multi-step workflow using
`ctx.step.run(...)`:

1. **gather-data** — pull this month's sales/expense totals from Postgres.
2. **run-agent** — runs the OpenAI Agents SDK bookkeeping assistant, a
   **planner + handoff, three-agent architecture** (see
   `ai_agents/api/financial_advisor_agent.py`):
   - `planner_agent` holds no tools; it only reads the request and hands
     off (`handoff()`) to whichever specialist fits.
   - `investigate_agent` holds the read-only tools
     (`get_monthly_summary`, `get_expense_breakdown_by_category`,
     `get_sales_breakdown_by_category`, `web_search`) and answers
     "how's my business doing / why" questions — this is what the
     proactive monthly-advice job routes to.
   - `record_agent` holds the record-creation tools
     (`create_expense_record`, `create_sales_record`, `deep_link`) and
     records a described transaction directly (no approval gate).

   The whole chain — planner hop, handoff, specialist's own tool calls —
   runs as one `Runner.run_streamed(planner_agent, ...)` call with
   `max_turns=10` and an `error_handlers={"max_turns": ...}` fallback.
   Both specialists return a structured `BookkeepingResult` pydantic model
   (`mode`, `summary`, `root_cause`, `recommendation`, `used_web_search`,
   `record_reference`). On ANY failure (not installed, no network, no API
   key, the live call itself erroring, or `max_turns` exceeded) it falls
   back to `ai_agents/rules/fallback_engine.py`, a fully deterministic,
   offline rule engine, so the job always produces useful advice.
3. **finalize** — mark the job `completed` and store the result.

Each step writes to `agent_logs` (`step_name`, `action_summary`,
`insights_generated`) and updates `agent_jobs.status`/`current_step` via
`repository/agent_jobs_repository.py`. Because Inngest memoizes
`step.run()` results internally *and* we persist the same progress to
Postgres, a retried invocation (crash, timeout, worker restart) resumes from
the last completed step instead of repeating billable/side-effecting work.
An `on_failure` handler marks the job `failed` with `error_details` once
retries are exhausted.

### Inngest integration assumptions (documented, per task instructions)

Verified against **inngest==0.5.19** (the latest on PyPI at the time this
was built) by actually installing it and inspecting real signatures:

- `inngest.Inngest(app_id=..., event_key=..., signing_key=..., is_production=...)`
- `client.create_function(fn_id=..., name=..., trigger=inngest.TriggerEvent(event=...), retries=...)` returns a decorator.
- Function handlers: `async def handler(ctx: inngest.Context, step: inngest.Step)`.
- `step.run(step_id, async_callable)` — memoized.
- `inngest.fast_api.serve(app, client, functions, serve_path="/api/inngest")`
  mounts the required routes into the FastAPI app.

If you upgrade `inngest` and an API shape has changed, `jobs/inngest_client.py`
and `jobs/financial_agent_job.py` are the only two files that need updating.

## Full Model Context Protocol (FastMCP, stdio)

`mcp_gateway/server.py` implements all 5 MCP primitives, verified against
**fastmcp==4.0.3**:

1. **Tools** — `log_sale`, `log_expense`, `trigger_financial_agent_job` (plus
   two bonus tools: `summarize_ledger_via_client_llm` for sampling, and
   `stream_job_logs` for the logging primitive).
2. **Resources** — `ledger://{org_id}/monthly.csv`, a resource *template*
   that reads live sales/expenses from Postgres and returns a raw CSV string.
3. **Prompts** — `financial_audit(org_id)`, which loads
   `ai_agents/prompts/financial_audit.md` via `ai_agents/prompt_loader.py` and
   pre-fills it with the org's current ledger CSV.
4. **Sampling** — `summarize_ledger_via_client_llm` calls
   `ctx.session.create_message(...)` (the standard MCP
   `sampling/createMessage` request) so the **connected MCP client's LLM**
   performs the completion and pays for it — this server never calls OpenAI
   directly for this tool. This is inherently interactive (a real MCP client
   must be connected and support sampling) so it isn't unit-tested end to
   end; `tests/unit/test_mcp_server.py` verifies the tool/resource/prompt are
   correctly *registered* instead.
5. **Logging** — every tool calls `await ctx.log(message, level="info")` (or
   `ctx.error(...)`), which streams structured log notifications back to the
   connected MCP client's log stream. `stream_job_logs` additionally re-emits
   a job's `agent_logs` rows as a sequence of log notifications on demand.

### Run the MCP server

```bash
python mcp_gateway/server.py
# or:
fastmcp run mcp_gateway/server.py
```

Connect any MCP-compatible client (Claude Desktop, the `mcp` CLI inspector,
etc.) over stdio by pointing it at that command.

### Package-name collisions, fixed

Two previously documented limitations in this codebase were package-name
collisions between our own directories and third-party SDKs of the same
name — both are now fixed by renaming our packages, not by working around
the collision:

- **`mcp` (SDK) vs. our own `mcp/` directory.** The `mcp` Python SDK (a
  dependency of `fastmcp`) installs as a top-level module named `mcp`. This
  repo used to have its own top-level `mcp/` directory (required by an
  earlier version of the spec to live at `mcp/server.py`), which — if given
  an `__init__.py` and imported as `mcp` before the SDK — shadowed the real
  SDK and broke `import fastmcp` entirely
  (`ModuleNotFoundError: No module named 'mcp.server'`, verified). The old
  workaround was to keep the directory package-less (no `__init__.py`) and
  always load `server.py` via `importlib.util.spec_from_file_location(...)`
  instead of a normal import.

  **Fix:** the directory is renamed to **`mcp_gateway/`**. It now has a
  normal `__init__.py` and is imported normally
  (`from mcp_gateway.server import mcp` — see
  `tests/unit/test_mcp_server.py`, which no longer needs the `importlib`
  workaround). `mcp_gateway/server.py` still correctly imports the real SDK
  internally (`from fastmcp import ...`, `from mcp.types import ...`) —
  those now unambiguously resolve to the third-party packages since our own
  package is no longer named `mcp`.

- **`agents` (SDK) vs. our own `agents/` directory.** The `openai-agents`
  PyPI package installs as a top-level module named `agents`. This repo
  used to have its own top-level `agents/` directory (also required by an
  earlier version of the spec). Because Python resolves a package's own
  name before importing its submodules, `import agents` from *inside* that
  package always resolved to itself, never to the SDK — so the real SDK was
  **structurally unreachable** no matter how it was installed or
  configured, and the code always fell back to the rule-based engine,
  treating "shadowed" exactly like "SDK unavailable."

  **Fix:** the directory is renamed to **`ai_agents/`**. `import agents`
  inside `ai_agents/api/financial_advisor_agent.py` now genuinely resolves
  to the real `openai-agents` SDK — see that file's updated docstring. The
  function still raises `AgentUnavailableError` (caught by the Inngest job
  step, which falls back to `ai_agents/rules/fallback_engine.py`) for the
  *ordinary* reasons an external API call can fail — not installed, no
  network, no `OPENAI_API_KEY`, or the live call itself erroring — so the
  system is exactly as resilient as before, but the SDK path now actually
  runs when it's genuinely configured, instead of being permanently
  unreachable by construction.
  `tests/unit/test_financial_advisor_agent.py` was updated to assert
  correct behavior under *either* outcome (a real SDK response, or a
  documented `AgentUnavailableError`) rather than asserting the SDK is
  always unreachable, since which one happens now depends on real
  environment configuration rather than an import bug.

If you rename either package again, re-run
`pytest tests/unit/test_mcp_server.py tests/unit/test_financial_advisor_agent.py -v`
and re-verify `import fastmcp` / `import agents` still resolve to the
intended packages before assuming it's safe.

## Idempotency, auth, and MCP tools all share the same services/repository code

`mcp_gateway/server.py`'s `log_sale`/`log_expense`/`trigger_financial_agent_job`
tools call the exact same `services.sales_service` / `services.expenses_service`
/ `services.agent_job_service` functions the HTTP routers use — so
validation and multi-tenant scoping behave identically whether a sale is
logged via the REST API or via an MCP client.

## Running locally

### Docker Compose (FastAPI + Redis + Inngest Dev Server)

```bash
cp .env.example .env   # fill in real MSSQL_*/OpenAI values
docker compose up --build   # (compose files are NOT updated for SQL Server; the supported path now is uvicorn, see below)
```

This starts:
- `redis` — Redis 7
- `inngest` — the Inngest Dev Server, pointed at `api:8000/api/inngest`
- `api` — the FastAPI app (also serves the Inngest handler at `/api/inngest`)
- `inngest-worker` — a second copy of the same image on a different port, for
  deployments that want to scale Inngest-invoked traffic separately from
  user-facing API traffic (both run the identical `core.fastapi_app:app`)

Visit `http://localhost:8288` for the Inngest Dev Server UI, and
`http://localhost:8000/docs` for the FastAPI OpenAPI docs.

### SQL Server environment variables (see `specs/13-sql-server-migration.md`)

Everything (auth, sales, expenses, agent jobs/logs, Inngest job steps, MCP server, agent tools) runs on
SQL Server; Supabase is gone. Run `../sql_server/01_foundation.sql` then `02_sales_expenses_agents.sql` then `03_products.sql`, `04_customers.sql`, `05_sale_items_cash_recordsale.sql`, `06_expenses_cash.sql` in SSMS first, then set either
`MSSQL_CONNECTION_STRING` (full ODBC string) or `MSSQL_SERVER`, `MSSQL_DATABASE` (default
`HandsellerDB`), `MSSQL_USER`/`MSSQL_PASSWORD` (empty user = Windows auth), `MSSQL_DRIVER`
(default `ODBC Driver 18 for SQL Server`), `MSSQL_TRUST_SERVER_CERTIFICATE`. Requires the
Microsoft ODBC driver on the machine running `uvicorn` (and the MCP server). `SUPABASE_*` variables no longer exist.
Optional real-DB tests: `RUN_MSSQL=1 pytest tests/sqlserver -v`.

### Locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn core.fastapi_app:app --reload
```

## Running tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/unit tests/integration -v      # fast, fully mocked — no network/DB required
pytest tests/e2e -v                          # skipped by default
RUN_E2E=1 pytest tests/e2e -v                # requires Redis/Inngest + real SQL Server (see below)
```

`tests/unit` and `tests/integration` replace every repository module with in-memory fakes
(`tests/fake_repos.py`, installed by an autouse fixture) that enforce `id`+`org_id` scoping exactly like
the SQL does, plus `fakeredis` for the idempotency middleware — no live network or database is touched.
`tests/unit/test_repository_sql_shapes.py` runs the REAL repositories against a recording `Db` to check
statements/parameters. `tests/sqlserver/` (gated by `RUN_MSSQL=1`) runs against a real SQL Server.
`tests/e2e/prompt-2..5` and `test_full_inngest_workflow.py` need real infrastructure (`RUN_E2E=1`, or
reachable SQL Server/Redis); their DB setup/cleanup goes through `tests/e2e/e2e_db.py`. They have NOT been run
against SQL Server (none available while porting).

> **Annotation:** earlier text described `tests/fakes.py` / `FakeSupabase` and "37 tests"; both are gone.

## Connecting an MCP client (stdio)

Example Claude Desktop config entry:

```json
{
  "mcpServers": {
    "handseller-bookkeeping": {
      "command": "python",
      "args": ["/absolute/path/to/mcp_gateway/server.py"],
      "env": { "MSSQL_SERVER": "localhost", "MSSQL_DATABASE": "HandsellerDB", "MSSQL_CONNECTION_STRING": "" }
    }
  }
}
```

## Production Readiness Review

At the end of building this system, a self-review pass was performed and the
following changes were made:

1. **Global exception handlers** added to `core/fastapi_app.py` for
   `StarletteHTTPException`, `RequestValidationError`, and a catch-all
   `Exception` handler that logs the full traceback server-side but returns
   a generic `500` to the client (never leaks internals).
2. **Health check endpoint** (`GET /health`) added that independently probes
   Redis and SQL Server connectivity (`checks.database`; was `checks.supabase`), used by the Dockerfile's `HEALTHCHECK`.
3. **Idempotency concurrency safety**: added a `SET NX EX 30` lock so two
   concurrent requests with the same `Idempotency-Key` can't both execute
   the handler — the loser gets `409 Conflict` instead of a duplicate write.
4. **Idempotency cache scoping**: cache keys are scoped per-org
   (`idempotency:{org_id}:{key}`) so two different tenants can never collide
   on the same key, and errors (5xx) are never cached, so a transient
   failure doesn't get "stuck" as a cached error response.
5. **Password hashing**: PBKDF2-HMAC-SHA256 with 200,000 iterations and a
   random 16-byte salt per user, using `hmac.compare_digest` for constant-time
   comparison (implemented directly to avoid adding a bcrypt/passlib
   dependency, since the task's dependency list didn't include one).
6. **JWT secret length**: default dev secret bumped to 32+ bytes to satisfy
   PyJWT's minimum-recommended HMAC key length and avoid a runtime warning.
7. **Structural IDOR elimination** double-checked across every repository
   function — confirmed via a regression test suite
   (`test_sales_multitenancy.py`, `test_ownership.py`) that cross-tenant
   reads/updates/deletes on the same id return 404, not the target org's data.
8. **Inngest `on_failure` handler** added so a job that exhausts all retries
   is explicitly marked `failed` with `error_details` in Postgres, rather
   than silently disappearing.
9. **Graceful AI degradation**: the financial-advisor job step catches
   *any* exception from the OpenAI Agents SDK call (network error, missing
   API key, the documented package-shadowing issue) and transparently falls
   back to a deterministic rule engine, so a user always gets advice even if
   the AI/network stack is fully down — this is exercised directly in
   `tests/unit/test_fallback_engine.py`.
10. **`mcp`/`agents` package-name collisions** identified, reproduced, root-
    caused, and **fixed** by renaming our own `mcp/` and `agents/`
    directories to `mcp_gateway/` and `ai_agents/` (see "Package-name
    collisions, fixed" above) — freeing `import mcp` and `import agents` to
    resolve to the real third-party SDKs instead of shadowing them.
    Regression-tested by `tests/unit/test_mcp_server.py` (all 5 MCP
    primitives still register correctly, now via a normal import) and
    `tests/unit/test_financial_advisor_agent.py` (the OpenAI Agents SDK
    path no longer raises `AgentUnavailableError` purely due to import
    shadowing — only for genuine unavailability: not installed, no
    network, no API key, or a failed live call).
11. **`.env.example`** includes every required variable with clearly fake
    placeholder values — no real secrets anywhere in the repo.
12. **CORS** left permissive (`allow_origins=["*"]`) for local development;
    flagged here explicitly as something to lock down to real origins
    before any production deployment.
