# Handseller Bookkeeping

A multi-tenant bookkeeping backend for small sellers: daily sales/expense
logging, monthly financial reports, expense analytics, an autonomous AI
financial advisor (OpenAI Agents SDK), and an MCP server that exposes the
same operations to external LLM clients (Claude Desktop, ChatGPT, etc).

## Architecture

Strict 3-tier separation, enforced by import direction (routers -> services ->
repository -> Supabase):

```
app/
  routers/        FastAPI route handlers only — extract request, call a
                   service, return the HTTP response. No DB access.
  services/       Business logic, validation, analytics, agent orchestration.
                   Delegates all persistence to repository/.
  repository/     The ONLY layer that executes Supabase queries. Every
                   read/update/delete on a tenant-owned table filters by
                   BOTH id and org_id in the same query (no check-then-fetch).
  agents/         OpenAI Agents SDK tools + the financial advisor agent
                   (falls back to a deterministic rule-based analysis when
                   the SDK / API key is unavailable, so the app and tests
                   run fully offline).
  mcp/            FastMCP server exposing app tools to external LLM clients.
  middleware/     Idempotency middleware (Auth is a FastAPI dependency in
                   app/core/auth.py rather than middleware, since it must run
                   before route-level org scoping decisions).
  schemas/        Pydantic request/response models.
  core/           Settings, Supabase client factory, JWT auth dependency.
tests/
  unit/           services/ calculations and agents/ tools with mocked
                   repositories.
  integration/    FastAPI TestClient tests against an in-memory fake Supabase
                   client — endpoint behavior, idempotency replay, org
                   scoping.
sql/schema.sql    Full Supabase Postgres schema.
```

## Database schema

See `sql/schema.sql`. Run it once in the Supabase SQL editor (or via the
Supabase CLI) against a fresh project. Tables: `users`, `orgs`,
`org_members` (backs `get_ownership()`), `sales`, `expenses`,
`idempotency_keys`, `agents`, `agent_logs` — with indexes on every `org_id`
and `(org_id, id)` pair used by scoped queries.

## Structural multi-tenancy

Every repository query that touches a single row filters by `id` AND `org_id`
in the same call, e.g.:

```python
client.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).execute()
```

There is no "fetch then compare org_id" anywhere in the codebase. A row
belonging to another org simply cannot be returned by the query, so a
mismatched `id`/`org_id` pair yields zero rows -> `404 Not Found` at the
service layer. `repository/org_repository.get_ownership(user_id, org_id)` is
used by the auth dependency to verify org membership before trusting a
client-supplied `org_id` JWT claim (mismatch -> `403 Forbidden`).

## Idempotency

`app/middleware/idempotency.py` enforces idempotency on `POST`/`PUT`/`PATCH`:

- Missing `Idempotency-Key` header -> `400 Bad Request`.
- `(key, user_id)` already recorded -> the stored `response_body` /
  `status_code` is returned immediately, without the route handler running.
- Otherwise the request executes normally, the response is captured and
  persisted to `idempotency_keys`, then returned to the caller.

## Endpoints

- `POST /sales` — log a sale (`amount`, `sale_date`, optional
  `voucher_reference`).
- `GET /sales/{sale_id}` — fetch a sale (org-scoped).
- `POST /expenses` — log an expense (`amount`, `category`, `expense_date`,
  optional `description`).
- `GET /expenses/{expense_id}` — fetch an expense (org-scoped).
- `GET /reports/monthly?month=&year=` — `total_sales`, `total_expenses`,
  `net_profit_loss`, `is_profitable`.
- `GET /reports/expense-breakdown?month=&year=` — per-category totals,
  percentage of overall spend, and `top_cost_drivers`.
- `POST /agent/run` — runs the autonomous financial advisor for a
  `month`/`year` and logs the execution to `agent_logs`.

All routes except `/health` and docs require `Authorization: Bearer <JWT>`
with `sub` (user id) and `org_id` claims. Mutating routes additionally
require `Idempotency-Key`.

### Error handling

- `422` — missing/invalid fields (Pydantic validation; response includes an
  `errors` list naming each field).
- `404` — a scoped `id` + `org_id` query returned no rows.
- `403` — the user is not a member of the `org_id` on their token.
- `400` — missing `Idempotency-Key` on a mutating request.

## Agentic AI layer

`app/agents/tools.py` exposes `fetch_monthly_report`,
`fetch_expense_breakdown`, and `fetch_recent_transactions` as plain
functions, reused by both the OpenAI Agents SDK path and the MCP server.
`app/agents/financial_advisor.py` wraps them as `@function_tool`s for an
`Agent` (via the `openai-agents` package) when `OPENAI_API_KEY` is set and
the package is installed; otherwise it runs a deterministic rule-based
analysis with the same output contract, so the API and tests work with no
network access. Every run — either path — is logged to `agent_logs` with
`agent_id`, `org_id`, `user_id`, `action_summary`, and structured
`insights_generated` (top cost drivers, cost-reduction suggestions, and a
pricing/volume recommendation).

## MCP server

`app/mcp/server.py` uses FastMCP to expose: `log_sale`, `log_expense`,
`get_monthly_report`, `analyze_expenses`, `run_financial_agent`. Each tool
takes explicit `org_id`/`user_id` arguments and re-verifies membership via
`get_ownership()` before touching data.

Run it:

```bash
python -m app.mcp.server
```

Connect from Claude Desktop by adding to its MCP config
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "handseller-bookkeeping": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/handseller-bookkeeping"
    }
  }
}
```

Any MCP-compatible client (Claude Desktop, ChatGPT with MCP support, etc.)
can then inspect the ledger and invoke financial operations as tool calls.

## Running the app

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in real Supabase/OpenAI credentials
uvicorn app.main:app --reload
```

Apply `sql/schema.sql` to your Supabase project before first use.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests never require network access or real credentials: unit tests mock the
repository layer, and integration tests run FastAPI's `TestClient` against
an in-memory fake Supabase client (see `tests/integration/conftest.py`).
