# E2E Scenarios — Prompt v2 (real infrastructure)

**This is prompt version 2** of the e2e suite. It supersedes the approach in
`tests/e2e/prompt-1/` for the specific goal of this prompt: prompt-1 wired
`FakeSupabase` + `fakeredis` (via the repo's `_wire_fakes` fixture) into
every test, which this prompt's instructions call a mistake for e2e tests.
Everything in `tests/e2e/prompt-2/` instead targets the **real** Supabase/
Postgres instance and the **real** Redis instance configured via `.env`
(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`), and one scenario
additionally requires a **live Inngest dev server** driving real event
delivery rather than an in-process step simulation. No test file in this
folder imports `FakeSupabase`, `fakeredis`, or anything from
`tests/fakes.py`.

See `RESULTS.md` in this folder for what actually happened when this suite
was run in this environment.

## Conventions

- Framework: `pytest` + FastAPI's `TestClient`, same HTTP surface as
  prompt-1, but `tests/e2e/prompt-2/conftest.py`'s `client` fixture does
  **not** wire fakes — `app.clients.get_supabase()` / `get_redis()` resolve
  to real clients exactly as they would under `docker compose up`.
- Cleanup: every fixture/test that creates a row tracks it via the
  `cleanup` fixture (`Cleanup.track_row(table, id, org_id)`), which deletes
  everything it tracked in a `yield`-based teardown — scoped by
  `id`+`org_id` (per CLAUDE.md's own multi-tenancy rule, so cleanup never
  becomes a blanket-delete backdoor) — and this teardown runs even if the
  test body raises, per pytest's fixture-finalizer semantics. Idempotency
  keys used by these tests are short-lived (24h TTL) and per-org-scoped, so
  they self-expire; the suite additionally exposes `redis_client`/
  `cleanup.track_redis_key` for a test that wants to delete a key
  immediately rather than waiting on TTL.
- No test asserts against `agents/`- or `mcp/`-directory package-collision
  behavior directly (that is a unit-level concern per CLAUDE.md, covered by
  `tests/unit/test_financial_advisor_agent.py` / `test_mcp_server.py`); this
  suite only cares that the *user-facing outcome* (job completes with a
  `source` field) is correct end-to-end.

## Scenarios documented

1. **Full sales + expense bookkeeping lifecycle for one org**
   (`test_bookkeeping_lifecycle_journey.py`)
   Registers a real org/user, creates two real `sales` rows and two real
   `expenses` rows, lists them, updates one of each, deletes one of each,
   and asserts the final real DB state reflects exactly the remaining,
   updated records. Exercises routers -> services -> repository -> real
   Supabase end-to-end for the core CRUD path.

2. **Cross-tenant isolation across the full product surface**
   (`test_cross_tenant_isolation_journey.py`)
   Two real orgs (A, B). Org A creates a real sale, expense, and agent job.
   Org B attempts to GET/PUT/DELETE each by exact id and must get `404`
   (never `403`, never `200`) — checked against the real Postgres rows, not
   an in-memory fake's filtering logic. Also asserts org A's sale survives
   org B's failed delete attempt, and that list endpoints never leak the
   other org's rows.

3. **Idempotent retry of a flaky mobile client, against real Redis**
   (`test_idempotent_retry_journey.py`)
   (a) POSTs `/sales` twice with the same `Idempotency-Key` against the
   real Redis instance and asserts exactly one row is created and the
   second response is byte-for-byte the cached replay of the first
   (`middleware/idempotency.py`'s actual cache-hit path, not a fake's
   dict). (b) Omits `Idempotency-Key` entirely -> `400`. (c) Reuses the
   same key across two different real orgs and confirms each org gets its
   own row (per-org key scoping: `idempotency:{org_id}:{key}` in the real
   Redis keyspace).

4. **Financial-advice background job lifecycle via real Inngest event
   delivery** (`test_financial_advice_job_journey.py`)
   Triggers `POST /agent-jobs/financial-advice` and asserts the immediate
   `202` + `job_id` contract (CLAUDE.md rule 3: agent work never runs
   synchronously in the request handler). Unlike prompt-1, this scenario
   does **not** call `jobs/financial_agent_job.py`'s step functions
   in-process — it only polls `GET /agent-jobs/{id}` and requires the real
   Inngest dev server (reachable at `INNGEST_BASE_URL`) to actually deliver
   the `financial/advice.requested` event to this app's mounted
   `/api/inngest` handler and drive the job to `completed`, asserting the
   final `result.source` is one of `openai_agent` / `rule_based_fallback`.
   Also asserts a second org gets `404` polling the first org's job id.
   This test is skipped (not faked, not simulated) when the Inngest dev
   server isn't reachable — see `RESULTS.md`.

5. **Auth and input-validation edge cases against the real `users` table**
   (`test_auth_and_validation_edge_cases.py`)
   Registering the same email twice is rejected `409` (real uniqueness
   check against real rows, not a fake dict's `in` check); wrong password
   on login -> `401`; unauthenticated request to a protected route ->
   `401`; malformed bearer token -> `401`; non-positive sale/expense amount
   -> `422`.

## Edge cases explicitly identified but intentionally not asserted

- **Redis genuinely unreachable**: per `specs/10-known-limitations.md` this
  is a documented, accepted gap (mutating requests currently 500 rather
  than degrading gracefully). Scenario 3 does not assert this failure mode
  as "correct" behavior; if Redis is unreachable in a given run, scenario 3
  fails honestly rather than being skipped or faked — see `RESULTS.md`.
- **Inngest dev server unreachable**: scenario 4 is explicitly skipped
  (with the real connection error recorded) rather than falling back to
  in-process step simulation, per this prompt's instructions to drive
  background-job scenarios through real event delivery only.
- **Supabase unreachable / placeholder URL**: every scenario's `_register`
  helper is the first real network call each test makes; if
  `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` are still placeholders or the host
  is unreachable, every scenario fails at that first call. This is recorded
  in `RESULTS.md` as "blocked: infra unreachable", not silently retried or
  swallowed.
