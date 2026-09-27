# E2E Scenarios — Prompt v1

This document identifies end-to-end user scenarios for the handseller
bookkeeping backend, derived from reading `specs/00-overview.md` through
`specs/10-known-limitations.md` and `CLAUDE.md`. Each scenario below is
implemented as one test script in this folder (`tests/e2e/prompt-1/`).

## Conventions followed

- Framework: `pytest` + FastAPI's `TestClient`, matching
  `tests/integration/*` (this repo's existing HTTP-level test style).
- Isolation: the autouse `_wire_fakes` fixture (`tests/conftest.py`) wires
  `FakeSupabase` and `fakeredis` into the app's client singletons, so these
  scripts run with no real network/DB/Redis/OpenAI/Inngest dependency —
  consistent with how `tests/integration/*` already runs, and with
  `specs/09-testing-strategy.md`'s statement that `FakeSupabase` is faithful
  enough to exercise real repository filtering (including the `id`+`org_id`
  double-scoping).
- Scope: unlike `tests/e2e/test_full_inngest_workflow.py` (which requires a
  live `docker compose up` stack and real Inngest, and is gated behind
  `RUN_E2E=1`), the scenarios here are **full user journeys across multiple
  endpoints in one flow** (register → transact → poll a job → verify
  isolation), exercised through the real HTTP surface via `TestClient`
  rather than unit-testing one function. This is "end-to-end" in the sense
  of a complete user scenario touching routers → services → repository →
  middleware together, while remaining runnable in this sandbox by default
  (no `RUN_E2E` gate needed, since no live external infra is required).
  Where a scenario's underlying job genuinely requires the live Inngest dev
  server to drive execution (rather than the fallback path), that is called
  out explicitly in the scenario below and in the test file's own skip
  guard.
- Shared helpers: reuse `tests/integration/conftest.py`'s
  `register_and_login` / `auth_headers`, and the `client` fixture, to stay
  consistent with existing integration tests rather than reinventing setup.

## Scenarios documented

1. **Full sales + expense bookkeeping lifecycle for one org**
   (`test_bookkeeping_lifecycle_journey.py`)
   A handseller registers an org, logs several sales and expenses, lists
   them, updates one of each, deletes one of each, and confirms the final
   state reflects exactly the remaining records. Covers the core CRUD path
   through routers → services → repository for both `sales` and `expenses`.

2. **Cross-tenant isolation across the full product surface**
   (`test_cross_tenant_isolation_journey.py`)
   Two separate orgs (A and B) each register, log sales/expenses, and
   trigger an agent job. The scenario asserts org B gets `404` (never `403`
   or `200`) when it tries to read/update/delete org A's sale, org A's
   expense, and org A's agent job by exact id — and that each org's list
   endpoints only ever return that org's own rows. Directly exercises the
   guarantee in `specs/03-multi-tenancy-security.md`.

3. **Idempotent retry of a flaky mobile client**
   (`test_idempotent_retry_journey.py`)
   Simulates a handseller on a bad connection: (a) POSTs `/sales` twice with
   the same `Idempotency-Key` (simulating a client retry after a lost
   response) and asserts only one sale row is ever created and the same
   cached response is replayed; (b) omits the `Idempotency-Key` header
   entirely and asserts `400`; (c) reuses the same key for a *different*
   org and confirms no cross-org cache collision (per-org key scoping).
   Directly exercises `specs/04-idempotency-redis.md`.

4. **Financial-advice background job lifecycle, including cross-tenant job
   access** (`test_financial_advice_job_journey.py`)
   A user logs sales/expenses, triggers `POST /agent-jobs/financial-advice`
   and gets `202` + a `job_id` immediately (never blocking on the LLM call,
   per `specs/05-background-jobs-inngest.md`), then the test directly
   drives the Inngest job function's steps in-process (no live Inngest dev
   server, consistent with `_wire_fakes`/no `RUN_E2E`) to simulate the
   worker completing the job, and polls `GET /agent-jobs/{id}` until
   `status == "completed"`, asserting the result carries a `source` field
   (`openai_agent` or `rule_based_fallback`) per the documented fallback
   behavior. Also asserts another org gets `404` polling that job id.

5. **Auth and input-validation edge cases across the registration/login/
   mutation surface** (`test_auth_and_validation_edge_cases.py`)
   Registering the same email twice is rejected (`409`); logging in with a
   wrong password is rejected (`401`); an unauthenticated request to a
   protected route is rejected (`401`); creating a sale/expense with a
   non-positive amount is rejected (`422`); and an authenticated user with
   a malformed/expired-looking bearer token is rejected. Covers the
   validation and auth edges implied by `services/*_service.py`'s
   `ValidationError`/`AuthError` handling and `routers/deps.py`.

## Assumptions and gaps

- `specs/` documents Redis being unreachable as an explicit **known,
  unfixed gap** (`10-known-limitations.md`) with no graceful-degrade path —
  this is not tested here since it would just assert today's `500`
  behavior, which the specs already call out as intentionally undocumented
  as "acceptable" rather than a scenario to lock in.
- There is no dedicated `/reports` or `/financial-report` HTTP endpoint in
  `routers/` — `financial_report_service.monthly_summary` is only reachable
  indirectly via the agent job's `gather-data` step, so scenario 4 exercises
  it that way rather than via a direct endpoint.
- The real OpenAI Agents SDK is structurally unreachable from inside this
  repo's own `agents/` package (see `specs/06-agents-layer.md` — the
  `agents` package-name collision), so in this sandboxed test environment
  the financial-advice job scenario always exercises the
  `rule_based_fallback` path, not `openai_agent`. The test asserts
  `source` is one of the two valid values rather than asserting a specific
  one, to stay correct in an environment where the collision is ever fixed.
- The true multi-step Inngest execution (a live dev server actually
  invoking `financial_advisor_job` via HTTP/event delivery) is already
  covered by the existing gated `tests/e2e/test_full_inngest_workflow.py`;
  scenario 4 here deliberately does not duplicate that live-infra
  requirement and instead documents/exercises the job's step functions and
  the polling contract directly, so it can run without `RUN_E2E=1`.
- Role-based permissions within an org (owner vs. member) are explicitly
  documented as unenforced today (`specs/03-multi-tenancy-security.md`), so
  no scenario here asserts role-based access control — there is none to
  test yet.
