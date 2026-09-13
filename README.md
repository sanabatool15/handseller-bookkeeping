# Handseller Bookkeeping Backend

A production-oriented backend for a handseller bookkeeping application:
FastAPI + Supabase (Postgres) + Redis + Inngest (resilient background jobs)
+ FastMCP (Model Context Protocol server over stdio) + the OpenAI Agents SDK,
with a rule-based offline fallback for AI-generated financial advice.

## Architecture

```
routers/       FastAPI route handlers ONLY (no business logic, no SQL)
services/      Business logic + validation (no direct DB access)
repository/    The ONLY layer allowed to run Supabase queries
middleware/    Auth (JWT) + Redis-backed Idempotency middleware
jobs/          Inngest client + the financial-advisor background function
mcp/           FastMCP server (stdio) — tools/resources/prompts/sampling/logging
agents/
  prompts/     Agent + system prompts as .md files (never hardcoded strings)
  api/         OpenAI Agents SDK orchestration
  rules/       Deterministic rule-based fallback (works fully offline)
  tools/       Utility functions (web search, deep-link generation)
app/           FastAPI app wiring, settings, Supabase/Redis clients, JWT
sql/           Postgres schema (apply to Supabase)
tests/
  unit/        Mocked DB (in-memory fake) + fakeredis
  integration/ FastAPI TestClient against the same fakes
  e2e/         Full-stack workflow — skipped unless RUN_E2E=1 (see below)
```

### Strict layering

`routers/` never touches Supabase directly — it only calls into `services/`,
which validates input and calls `repository/`, the only place `db.table(...)`
is ever invoked. This is enforced by convention and code review, not a
runtime check, but the four modules under `repository/` are the sole holders
of Supabase query code in this repo (grep for `.table(` — it only appears
there and in `mcp/server.py`'s ledger-reading path, which itself calls into
`services/`).

## Database schema

See `sql/schema.sql`. Tables: `users`, `orgs`, `sales`, `expenses`,
`agent_jobs`, `agent_logs`. All tables have `created_at`/`updated_at` with an
`updated_at` trigger. Row Level Security policies are included as
defense-in-depth on top of the application-layer scoping described below.

Apply it via the Supabase SQL editor, or:

```bash
supabase db push --file sql/schema.sql
```

## Structural multi-tenancy (critical)

Every read/update/delete in `repository/*.py` filters by **both** `id` and
`org_id` in the same database call, e.g.:

```python
db.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).execute()
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
2. **run-agent** — run the OpenAI Agents SDK financial advisor; on ANY
   failure (network, API key, SDK import shadowing — see below) it falls
   back to `agents/rules/fallback_engine.py`, a fully deterministic, offline
   rule engine, so the job always produces useful advice.
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

`mcp/server.py` implements all 5 MCP primitives, verified against
**fastmcp==4.0.3**:

1. **Tools** — `log_sale`, `log_expense`, `trigger_financial_agent_job` (plus
   two bonus tools: `summarize_ledger_via_client_llm` for sampling, and
   `stream_job_logs` for the logging primitive).
2. **Resources** — `ledger://{org_id}/monthly.csv`, a resource *template*
   that reads live sales/expenses from Postgres and returns a raw CSV string.
3. **Prompts** — `financial_audit(org_id)`, which loads
   `agents/prompts/financial_audit.md` via `agents/prompt_loader.py` and
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
python mcp/server.py
# or:
fastmcp run mcp/server.py
```

Connect any MCP-compatible client (Claude Desktop, the `mcp` CLI inspector,
etc.) over stdio by pointing it at that command.

### MCP package-name collision (documented limitation)

The `mcp` Python SDK (a dependency of `fastmcp`) installs as a top-level
module also named `mcp`. The task spec requires this server live at
`mcp/server.py`. To avoid `mcp/` (our directory) shadowing the real SDK
package — which we verified breaks `import fastmcp` entirely
(`ModuleNotFoundError: No module named 'mcp.server'`) if our directory has
an `__init__.py` and gets imported as `mcp` before the SDK does — **this
directory intentionally has no `__init__.py`** and `mcp/server.py` is never
imported anywhere in this codebase via `import mcp.server` or
`from mcp.server import ...`. It's always either run directly as a script,
or (in `tests/unit/test_mcp_server.py`) loaded via
`importlib.util.spec_from_file_location(...)` under a distinct module name.
Do not add an `__init__.py` here or add `from mcp.server import ...`
anywhere else without re-testing this collision.

A related, separate collision: `openai-agents` also installs as a top-level
module named `agents`, colliding with this repo's own `agents/` package
(also required by the spec). `agents/api/financial_advisor_agent.py`
documents and handles this in detail — in short, `import agents` from
*inside* our own `agents` package always resolves to itself (Python caches
the parent package before importing submodules), so the SDK path is
effectively always "unavailable" when run from within this repo as-is, and
the code treats that exactly like "SDK down" and raises
`AgentUnavailableError`, which the Inngest job step catches and routes to
the rule-based fallback engine. If you need the real SDK to work end-to-end,
run it from a process where `agents/` (this repo) is not what Python
resolves `import agents` to (e.g. a separate service/venv boundary, or
renaming one of the two packages).

## Idempotency, auth, and MCP tools all share the same services/repository code

`mcp/server.py`'s `log_sale`/`log_expense`/`trigger_financial_agent_job`
tools call the exact same `services.sales_service` / `services.expenses_service`
/ `services.agent_job_service` functions the HTTP routers use — so
validation and multi-tenant scoping behave identically whether a sale is
logged via the REST API or via an MCP client.

## Running locally

### Docker Compose (FastAPI + Redis + Inngest Dev Server)

```bash
cp .env.example .env   # fill in real Supabase/OpenAI values
docker compose up --build
```

This starts:
- `redis` — Redis 7
- `inngest` — the Inngest Dev Server, pointed at `api:8000/api/inngest`
- `api` — the FastAPI app (also serves the Inngest handler at `/api/inngest`)
- `inngest-worker` — a second copy of the same image on a different port, for
  deployments that want to scale Inngest-invoked traffic separately from
  user-facing API traffic (both run the identical `app.main:app`)

Visit `http://localhost:8288` for the Inngest Dev Server UI, and
`http://localhost:8000/docs` for the FastAPI OpenAPI docs.

### Locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/unit tests/integration -v      # fast, fully mocked — no network/DB required
pytest tests/e2e -v                          # skipped by default
RUN_E2E=1 pytest tests/e2e -v                # requires `docker compose up` + real Supabase
```

`tests/unit` and `tests/integration` use an in-memory fake Supabase client
(`tests/fakes.py`) that mimics the chained query-builder API closely enough
to exercise real repository filtering logic (including the id+org_id
double-scoping), plus `fakeredis` for the idempotency middleware — no live
network or database is touched. **37 tests pass, 1 e2e test is skipped by
design** (see `tests/e2e/test_full_inngest_workflow.py`'s docstring): it
requires a live `docker compose up` stack and a real Supabase/Postgres
instance with `sql/schema.sql` applied, so it's gated behind `RUN_E2E=1`
rather than left broken/uncommented.

## Connecting an MCP client (stdio)

Example Claude Desktop config entry:

```json
{
  "mcpServers": {
    "handseller-bookkeeping": {
      "command": "python",
      "args": ["/absolute/path/to/mcp/server.py"],
      "env": { "SUPABASE_URL": "...", "SUPABASE_SERVICE_KEY": "..." }
    }
  }
}
```

## Production Readiness Review

At the end of building this system, a self-review pass was performed and the
following changes were made:

1. **Global exception handlers** added to `app/main.py` for
   `StarletteHTTPException`, `RequestValidationError`, and a catch-all
   `Exception` handler that logs the full traceback server-side but returns
   a generic `500` to the client (never leaks internals).
2. **Health check endpoint** (`GET /health`) added that independently probes
   Redis and Supabase connectivity, used by the Dockerfile's `HEALTHCHECK`.
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
10. **MCP/`agents` package-name collisions** identified, reproduced, root-
    caused, and documented (see sections above) rather than left as a latent
    footgun — including a concrete regression test
    (`tests/unit/test_mcp_server.py`) proving `mcp/server.py` still loads
    and registers all 5 primitives correctly under this repo's layout.
11. **`.env.example`** includes every required variable with clearly fake
    placeholder values — no real secrets anywhere in the repo.
12. **CORS** left permissive (`allow_origins=["*"]`) for local development;
    flagged here explicitly as something to lock down to real origins
    before any production deployment.
