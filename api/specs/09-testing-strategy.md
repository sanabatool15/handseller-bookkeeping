# Testing Strategy

## New direction: real dependencies instead of fakes

The plan going forward is to test against **real infrastructure** — a real
Supabase/Postgres instance and a real Redis instance — rather than the
in-memory fakes (`tests/fakes.py`'s `FakeSupabase`, `fakeredis`) used
previously. Fakes verify the application's own query-building and filtering
logic, but they cannot catch bugs in the real Postgres/Supabase behavior
itself (RLS policies, constraints, real query semantics) or real
Redis-protocol edge cases — and they can silently diverge from the real
client's behavior as dependency versions change.

This requires a fresh test setup that doesn't exist yet:

- A real test database (a dedicated Supabase/Postgres project or a local
  Postgres instance with `sql/schema.sql` applied), reset to a known state
  between test runs.
- A real Redis instance reachable from the test environment (rather than
  `fakeredis`), with idempotency keys/locks cleared between runs.
- Test fixtures updated to point `set_supabase`/`set_redis` at real clients
  configured against this test infrastructure instead of the in-memory
  fakes, for both `tests/unit/` and `tests/integration/`.

This is documented here as the direction to build toward — the fakes-based
setup below is what currently exists and runs, not what the plan calls for
long-term.

## What currently exists (fakes-based, to be replaced)

Three tiers, exactly matching the spec's required folder split:

- **`tests/unit/`** — tests a single function/module in isolation, with all
  external dependencies (the Supabase client, Redis, the OpenAI Agents SDK)
  mocked or faked. Covers: `sales_service`, `expenses_service`,
  `financial_report_service` calculations, `ownership` scoping logic,
  `fallback_engine`, `financial_advisor_agent`'s SDK-detection behavior,
  `prompt_loader`, `ai_agents/tools/`, and `mcp_gateway/server.py`'s primitive
  registration.
- **`tests/integration/`** — drives the app through FastAPI's `TestClient`,
  exercising real routing + middleware + service + repository code paths
  together, still against fakes (no real network). Covers: the full
  auth flow (register/login), sales multi-tenancy (cross-org 404s),
  idempotency replay/locking, and the agent-jobs router.
- **`tests/e2e/`** — a single test
  (`test_full_inngest_workflow.py`) that drives the *actual* HTTP API
  against a live `docker compose up` stack (real Inngest Dev Server, real
  Redis, and a real reachable Supabase/Postgres instance) end to end:
  register → log a sale → trigger the financial-advice job → poll until
  Inngest actually completes it.

`tests/fakes.py` provides `FakeSupabase` — an in-memory implementation of
Supabase's chained query-builder interface
(`db.table(x).select(...).eq(...).execute()`) that applies `.eq(...)`
filters against an in-memory list of rows, so it exercises real repository
filtering logic (including the id+org_id double-scoping) rather than just
recording that a mock was called. `fakeredis` provides an in-memory
Redis-compatible client for the idempotency middleware tests. Under the new
direction above, both are to be replaced with real clients pointed at real
test infrastructure.

`tests/e2e` is currently gated behind `RUN_E2E=1` because it requires a
live Inngest Dev Server, a real reachable Supabase/Postgres instance with
`sql/schema.sql` already applied, and real Redis — infrastructure not
available by default in every environment. It's written in full and
correctly targets the real system, just skipped via `pytest.mark.skipif`
unless `RUN_E2E=1` is set, so `pytest` runs clean by default and
`RUN_E2E=1 pytest tests/e2e -v` gives a genuine end-to-end check once the
real stack (`docker compose up`) is running.

## Running the tests

```bash
pip install -e ".[dev]"
pytest tests/unit tests/integration -v      # fast, no network/DB required — 37 passing
pytest tests/e2e -v                          # skipped by default
RUN_E2E=1 pytest tests/e2e -v                # requires: docker compose up (see 08-infrastructure-docker.md)
```

## What to do when you change something

- **Changed `repository/*.py` or anything touching multi-tenancy?** Run
  `pytest tests/unit/test_ownership.py tests/integration/test_sales_multitenancy.py -v`
  before anything else. See `03-multi-tenancy-security.md` for what a
  regression looks like (a cross-org request returning 200 or 403 instead
  of 404).
- **Changed `middleware/idempotency.py`?** Run
  `pytest tests/integration/test_idempotency.py -v`.
- **Changed `mcp_gateway/server.py`?** Run `pytest tests/unit/test_mcp_server.py -v`
  — this is the regression test for the (now-fixed) `mcp` package-name
  collision described in `07-mcp-server.md`; it proves the server still
  loads and registers all 5 primitives via a normal
  `from mcp_gateway.server import ...` import.
- **Added a new mutating endpoint or table?** Add both a unit test (service
  logic, mocked/faked repository) and an integration test (`TestClient`,
  via `tests/fakes.py`) — see the existing `sales`/`expenses` tests as the
  template to follow.
- **Changed anything in `jobs/` or the Inngest integration?** The unit
  tests can only cover the fallback path and pure logic (Inngest itself
  isn't faked) — a real behavioral check of the multi-step workflow
  requires running `tests/e2e/test_full_inngest_workflow.py` with
  `RUN_E2E=1` against a real `docker compose up` stack.
