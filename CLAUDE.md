# CLAUDE.md

Guidance for Claude Code (or any AI agent) making future changes to this
repository. This file is the operating manual for this codebase — read it
before making changes, not just the README. The README explains what the
system does and how to run it; this file exists to keep future changes from
silently reintroducing bugs that were already found and fixed once.

## What this is

Agentic bookkeeping backend for a handseller business: FastAPI + Supabase
(Postgres) + Redis (idempotency) + Inngest (resilient background jobs) +
FastMCP (MCP server over stdio) + the OpenAI Agents SDK with a deterministic
offline fallback. Full architecture, schema, and setup instructions are in
`README.md` — this file assumes you've read it and focuses on rules and traps.

This branch (`variant-5`) is the "final" implementation in a 5-step prompt
ladder (see the project's `Prompt_Ladder_Final.docx` if present, or ask the
user) — it is the most complete and the one intended for real production
iteration. Do not port changes here from `variant-1`..`variant-4`; those are
earlier/simpler experiments kept only for comparison, not upstream branches.

## Non-negotiable architectural rules

These are enforced by convention/code review, not a runtime check — so it is
entirely possible to write code that violates them and have it still run.
Do not do this even under time pressure or when asked to "just make it work":

1. **Layering is one-directional and strict:**
   `routers/` → `services/` → `repository/`.
   - `routers/*.py`: HTTP only (parse request, call a service, return a
     response/HTTPException). No business logic, no `db.table(...)` calls.
   - `services/*.py`: validation + business logic + calling `repository/`.
     Never imports `app.clients.get_supabase` or calls `.table(` directly.
   - `repository/*.py`: the **only** place that talks to Supabase.
   Before adding a new feature, ask which layer it belongs to. If a router
   needs a new capability, add it to a service; if a service needs new data
   access, add it to a repository — don't take a shortcut "just this once."

2. **Every repository query that reads/updates/deletes a specific row MUST
   filter by `id` AND `org_id` in the same call.** This is the entire
   multi-tenancy security model:
   ```python
   db.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).execute()
   ```
   Never write `fetch_by_id(id)` and then compare `.org_id` afterward in
   Python (check-then-fetch) — that is the exact vulnerability this system
   was rebuilt to eliminate across the prompt ladder. `repository/base.py`
   has a shared `get_ownership(db, table, record_id, org_id) -> bool` helper
   — use it, don't reinvent ownership checks per-repository.
   A record belonging to another org must come back as **404**, never 403 —
   403 leaks that the record exists; 404 doesn't. This is regression-tested
   in `tests/unit/test_ownership.py` and
   `tests/integration/test_sales_multitenancy.py` — if you change this
   behavior, update those tests deliberately, don't just make them pass.

3. **Agent tasks never run synchronously inside an HTTP request handler.**
   Anything that calls the OpenAI Agents SDK (or any slow/unreliable
   external call) goes through an Inngest step function
   (`jobs/financial_agent_job.py`), triggered by the router returning
   `202 Accepted` + a `job_id` immediately. If you add a new AI-driven
   feature, follow the same pattern: create an `agent_jobs` row, fire an
   Inngest event, poll for status — don't call the LLM inline in a router.

4. **Idempotency-Key is required on every mutating endpoint** (POST/PUT/
   PATCH) via `middleware/idempotency.py`. If you add a new mutating route,
   it automatically goes through this middleware — don't bypass it, and
   don't cache error responses (5xx) as if they were successful (the
   middleware already avoids this; keep it that way if you touch it).

5. **Agent/system prompts live in `agents/prompts/*.md`, never as Python
   string literals.** If you're tempted to inline a prompt string in
   `agents/api/` or `jobs/`, stop — add or edit a `.md` file and load it via
   `agents/prompt_loader.py` instead.

## Two package-name collisions — read before touching imports

These are real, previously-reproduced bugs, not theoretical:

- **`mcp/` (this repo's directory) vs. the `mcp` PyPI package** (a dependency
  of `fastmcp`). If `mcp/` ever gets an `__init__.py` and gets imported as a
  package before the real `mcp` SDK is imported, `import fastmcp` breaks with
  `ModuleNotFoundError: No module named 'mcp.server'`. **Do not add
  `mcp/__init__.py`.** Never write `from mcp.server import ...` or
  `import mcp.server` elsewhere in the codebase — always run
  `mcp/server.py` as a script, or load it via `importlib.util` (see
  `tests/unit/test_mcp_server.py` for the pattern) if you need to test it.

- **`agents/` (this repo's directory) vs. the `openai-agents` PyPI package**,
  which also installs as a top-level `agents` module. From *inside* this
  repo's own `agents/` package, `import agents` always resolves to itself
  (Python resolves the parent package first), so the real SDK is effectively
  never reachable from within `agents/api/financial_advisor_agent.py` as
  currently structured. The code treats this exactly like "SDK unavailable"
  and falls back to `agents/rules/fallback_engine.py`. If you need the real
  SDK to actually run (not just fall back), it requires a process/venv
  boundary where `agents/` (this repo) isn't what `import agents` resolves
  to — e.g. run the agent-calling code as a separate service, or rename one
  of the two packages. Don't "fix" this by adding sys.path hacks inside the
  request path; that's a maintenance trap. Escalate to a real architectural
  decision instead (rename this repo's package, or isolate the SDK call in
  its own process) if you need the live SDK working end-to-end.

## Before you touch specific things

- **Changing `repository/*.py`**: re-run
  `pytest tests/unit/test_ownership.py tests/integration/test_sales_multitenancy.py -v`
  after any change here. If a cross-tenant test starts returning 403 or 200
  instead of 404, you've reintroduced the check-then-fetch bug.
- **Changing `middleware/idempotency.py`**: re-run
  `pytest tests/integration/test_idempotency.py -v`. Keep cache keys scoped
  per-org (`idempotency:{org_id}:{key}`) and never cache a 5xx response.
- **Changing `jobs/financial_agent_job.py` or `jobs/inngest_client.py`**:
  these are the two files documented as needing updates if `inngest`'s API
  shape changes on upgrade (verified against `inngest==0.5.19` — see
  README's "Inngest integration assumptions"). Re-verify against the
  installed version's actual signatures rather than assuming the README's
  snippet still matches after a dependency bump.
- **Changing `mcp/server.py`**: keep it runnable as a standalone script
  and re-run `pytest tests/unit/test_mcp_server.py -v` to confirm all 5 MCP
  primitives (tools, the `ledger://` resource, the `financial_audit` prompt,
  sampling, logging) are still registered correctly.
- **Adding a new mutating endpoint**: it must (a) require and honor
  `Idempotency-Key` (automatic via the middleware, don't opt out), (b) go
  through a service, (c) have its repository calls scoped by `id`+`org_id`
  if it touches an existing record, (d) return 404 (not 403) for
  cross-tenant access, (e) get a unit test (service, mocked repo) and an
  integration test (`TestClient`, `tests/fakes.py`).
- **CORS is currently `allow_origins=["*"]`** in `app/main.py` — this is
  flagged in the README's Production Readiness Review as dev-only. Lock this
  down to real origins before any actual production deployment; don't leave
  it wildcard and call it "done."
- **Password hashing** is hand-rolled PBKDF2-HMAC-SHA256 (`app/security.py`
  or wherever it lives) specifically because no bcrypt/passlib dependency was
  in scope. If you add one later, migrate deliberately (existing password
  hashes won't verify against a different scheme) rather than silently
  switching.

## Running things

See `README.md` for full instructions. Quick reference:

```bash
# tests (fast, no network/DB required)
pip install -e ".[dev]"
pytest tests/unit tests/integration -v

# e2e (needs docker compose up + real Supabase with sql/schema.sql applied)
RUN_E2E=1 pytest tests/e2e -v

# run the app
cp .env.example .env   # fill in real Supabase/Redis/OpenAI/Inngest values
docker compose up --build
# or: uvicorn app.main:app --reload

# run the MCP server standalone
python mcp/server.py
```

Never commit a filled-in `.env` — only `.env.example` with placeholder
values belongs in the repo.

## When making production changes

1. Read the relevant section of `README.md` first (architecture, schema,
   the specific subsystem you're touching).
2. Check this file's "before you touch specific things" list for that area.
3. Make the change inside the correct layer (routers/services/repository) —
   don't take a shortcut that crosses layers "just this once."
4. Run the targeted tests for that area, then the full fast suite
   (`pytest tests/unit tests/integration -v`) before considering it done.
5. If you touch `sql/schema.sql`, remember RLS policies and the
   `updated_at` trigger pattern already established there — new tables
   should follow the same conventions (see existing tables for the pattern).
6. Update `README.md` if you change externally-visible behavior (new env
   var, new endpoint, new assumption about a third-party SDK version) —
   keep the "Production Readiness Review" and "documented limitations"
   sections honest as the system evolves; don't let them go stale.
