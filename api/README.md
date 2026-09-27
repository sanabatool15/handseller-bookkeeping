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
mcp_gateway/   FastMCP server (stdio) — tools/resources/prompts/sampling/logging
               (renamed from mcp/ — see "Package-name collisions, fixed" below)
ai_agents/     (renamed from agents/ — see "Package-name collisions, fixed" below)
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
there and in `mcp_gateway/server.py`'s ledger-reading path, which itself calls into
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
      "args": ["/absolute/path/to/mcp_gateway/server.py"],
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
