# E2E Scenarios — Prompt v3 (narrated real infrastructure)

**This is prompt version 3** of the e2e suite. It targets the exact same
five scenarios, against the exact same real infrastructure, as
`tests/e2e/prompt-2/` — real Supabase/Postgres, real Redis, and (for
scenario 4) a live Inngest dev server, with no `FakeSupabase`, `fakeredis`,
or in-process job simulation anywhere in this folder. What changes in
prompt-3 is entirely about **legibility of the run**, not what is being
tested or how it talks to infrastructure.

## Scenarios covered (identical coverage to prompt-2)

1. **Full sales + expense bookkeeping lifecycle for one org**
   (`test_bookkeeping_lifecycle_journey.py`) — register, create two sales
   and two expenses, list, update one of each, delete one of each, assert
   final state.
2. **Cross-tenant isolation across the full product surface**
   (`test_cross_tenant_isolation_journey.py`) — org B must get `404` (never
   `403`/`200`) reading/updating/deleting org A's sale, expense, and agent
   job by exact id; list endpoints never leak the other org's rows.
3. **Idempotent retry of a flaky mobile client, against real Redis**
   (`test_idempotent_retry_journey.py`) — same `Idempotency-Key` posted
   twice creates exactly one row and replays the cached response; a missing
   key is rejected `400`; the same key reused across two orgs never
   collides (`idempotency:{org_id}:{key}` scoping).
4. **Financial-advice background job lifecycle via real Inngest event
   delivery** (`test_financial_advice_job_journey.py`) — `POST
   /agent-jobs/financial-advice` returns `202` + `job_id` immediately;
   polling `GET /agent-jobs/{id}` only completes once the real Inngest dev
   server has actually delivered the event and driven the job to
   `completed`; skipped (not faked) when the dev server isn't reachable.
5. **Auth and input-validation edge cases against the real `users` table**
   (`test_auth_and_validation_edge_cases.py`) — duplicate email `409`, wrong
   password `401`, unauthenticated request `401`, malformed bearer token
   `401`, non-positive sale/expense amount `422`.

## What's different from prompt-2

Prompt-2 proved the suite could target real infrastructure correctly.
Prompt-3 keeps that exact behavior and adds three things aimed purely at
making a run (or a failure) legible without a debugger:

1. **Narrated output.** Every test now takes a `story` fixture
   (`tests/e2e/prompt-3/conftest.py`) and calls `story.say(...)` before and
   after each meaningful action — "Registering user X for org Y",
   "POSTing sale of amount Z", "Asserting status 201", "Polling
   GET /agent-jobs/{id} ...". Running `pytest -v -s` against this folder
   produces a readable, chronological story of what each test is doing,
   not silent execution punctuated only by a final pass/fail line.
   Prompt-2's tests had no equivalent narration — they were correct but
   silent.

2. **Self-explanatory failures.** Every assertion in prompt-2 was a bare
   `assert resp.status_code == 201, resp.text` (or no message at all).
   Prompt-3 replaces every assertion with a shared `expect(condition, *,
   request_desc, response, message)` helper (defined identically in each
   test file, to avoid pytest conftest-module import collisions across
   directories) that, on failure, always raises an `AssertionError`
   containing:
   - the actual request that was sent (method, path, and JSON body/headers
     that matter),
   - the actual response status code received, and
   - the actual response body received,
   in addition to a plain-English description of what was expected. A
   failing test never reads as a bare `assert 409 == 201` — it reads as
   "registering a duplicate email should return 409 Conflict / request
   sent: POST /auth/register json={...} / response status: 500 / response
   body: {...}".

3. **Created-record logging before teardown, and one refreshed-per-run log
   file.** The `cleanup` fixture's `Cleanup` class (in `conftest.py`) now
   logs the full record (table, id, org_id, and the fields the test passed
   it — e.g. amount/category/email) via the test's `story` narrator
   immediately before deleting it in teardown, so the log retains a record
   of what existed during the run even after the real DB rows are gone.
   All of this narration — every step, every assertion, every
   created/deleted record — is captured, via a dedicated
   `logging.FileHandler(..., mode="w")` wired up in `conftest.py`'s
   `pytest_configure` hook, into a single file:
   **`tests/e2e/prompt-3/test_run.log`**. That handler opens in write
   (truncate) mode at the start of every pytest invocation that collects
   this folder, so each run leaves behind only its own most recent,
   complete log — never a mix of an old run's content and a new one's.

Nothing about scenario coverage, the real-infra fixture wiring
(`_wire_fakes` override shadowing the repo-root autouse fixture of the same
name), or the `id`+`org_id`-scoped, reverse-order teardown discipline
changed from prompt-2 — those are carried over unmodified, per CLAUDE.md's
multi-tenancy rule and per this prompt's instruction not to weaken any of
that.

## What was actually executed in this environment vs. what remains untested

This work was done in a remote sandbox session. Before writing any of the
above, the same three infrastructure dependencies were probed directly,
exactly as they were for prompt-2:

- **Redis** (`redis://localhost:6379/0`): `ConnectionError` — connection
  refused. No Redis server runs in this sandbox.
- **Inngest dev server** (`http://localhost:8288`): `curl` ->
  "Couldn't connect to server" (connection refused). No dev server runs in
  this sandbox.
- **Supabase** (`SUPABASE_URL` from `.env`, still the placeholder
  `https://your-project.supabase.co` copied from `.env.example` — no real
  project is provisioned here): `httpx.ProxyError: 502 Bad Gateway` from
  the sandbox's own egress proxy.

**Conclusion: identical to prompt-2 — none of the three required real
services are reachable from this sandbox.** This suite was then actually
run with `pytest -v -s` against that reality (see `test_run.log` in this
folder for the real, unedited output of that run). The log shows genuine
connection/proxy failures surfacing through the app's real
`supabase.Client` and `redis.asyncio` calls, narrated step-by-step up to
the point each test's first real network call fails — it does **not**
show a fabricated "everything passed" story. Scenario 4
(`test_financial_advice_job_journey.py`) is skipped, not faked, per its
`pytest.mark.skipif` guard, because `INNGEST_BASE_URL` is unreachable;
per this prompt's own design that scenario is never simulated in-process.

The two auth-only edge cases that need no DB/Redis at all
(`test_unauthenticated_request_to_protected_route_is_rejected`,
`test_malformed_bearer_token_is_rejected`) are expected to be the only
scenarios that can genuinely pass in this sandbox, since `AuthMiddleware`
rejects a missing/malformed bearer token purely in-process before any
Supabase/Redis call is made — see `test_run.log` for the actual outcome.

**Everything else — the full bookkeeping lifecycle, cross-tenant
isolation, all three idempotency sub-scenarios, the real-Inngest job
lifecycle, and the DB-backed auth/validation edge cases — is written
correctly and completely against real clients, and is ready to run, but
remains genuinely untested pending real infrastructure.** The user's own
stated plan is to run this suite once, end-to-end, against their real
local stack (`docker compose up`, real Supabase credentials in `.env`) and
confirm every scenario passes there themselves. Nothing in this folder
claims that verification already happened.
