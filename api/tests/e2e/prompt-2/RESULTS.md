# Results — prompt-2 real-infra e2e run

Run date: 2026-09-17. Command: `python -m pytest tests/e2e/prompt-2 -v`.

## Environment check performed before writing any conclusions

This is a remote sandbox session. Before assuming any infra worked, each
service was probed directly:

- **`.env`**: did not exist; only `.env.example` was present. Copied
  `.env.example` -> `.env` (placeholder values, e.g.
  `SUPABASE_URL=https://your-project.supabase.co`) so the app's real
  `pydantic_settings` config loader has something to read — this repo has
  no real Supabase project provisioned in this sandbox.
- **Redis**: `redis.from_url("redis://localhost:6379/0").ping()` ->
  `ConnectionError` (`Error 111 connecting to localhost:6379. Connect call
  failed`). No Redis server is running in this sandbox.
- **Supabase**: `db.table("users").select("*").limit(1).execute()` against
  the configured (placeholder) `SUPABASE_URL` ->
  `httpx.ProxyError: 502 Bad Gateway`, with the sandbox's egress proxy
  additionally reporting `connect_rejected (the egress proxy denied the
  CONNECT (organization policy) or could not reach the destination)` for
  `your-project.supabase.co:443`. There is no real Supabase project
  reachable from this sandbox, by policy and by absence of a real project.
- **Inngest dev server**: `curl http://localhost:8288` ->
  `Couldn't connect to server` (connection refused). No Inngest dev server
  is running in this sandbox.

**Conclusion: none of the three required real services (Supabase, Redis,
Inngest dev server) are reachable in this environment.** This matches the
task's own stated expectation for a sandbox session. The rest of this
document reports what actually happened when the suite was run against
that reality — nothing below is fabricated or backfilled to look green.

## Important fix made to the test harness itself before results are meaningful

The repo's own `tests/conftest.py` defines an **autouse** fixture named
`_wire_fakes` that silently injects `FakeSupabase` + `fakeredis` into
`app.clients`'s singletons for *every* test collected under `tests/`,
including (by default) anything under `tests/e2e/prompt-2/`. The first run
of this suite passed 10/12 tests — which on inspection turned out to be
because they were **silently running against the fakes**, not real infra,
despite this suite's own `conftest.py` never importing a fake. This is
exactly the failure mode this task warned about ("treat any use of fakes as
a mistake").

Fix: `tests/e2e/prompt-2/conftest.py` defines its own autouse fixture of
the **same name** (`_wire_fakes`), which pytest fixture resolution resolves
to the closest conftest — this shadows the repo-root fixture for every test
under this directory and re-points `app.clients`'s singletons at real
`supabase.create_client(...)` / `redis.asyncio.from_url(...)` clients built
straight from `.env`, before each test runs. After this fix, the same run
produced entirely different (and honest) results below.

## Actual results after the fix (real clients, infra unreachable)

```
9 failed, 2 passed, 1 skipped, 20 warnings in 8.63s
```

| Scenario | Test | Result | Why |
|---|---|---|---|
| 1. Bookkeeping lifecycle | `test_full_bookkeeping_lifecycle` | **FAILED** | `httpx.ProxyError: 502 Bad Gateway` on the first `/auth/register` call's `db.table("users").select(...)` (real Supabase unreachable) |
| 2. Cross-tenant isolation | `test_cross_tenant_isolation` | **FAILED** | Same — register (org A) never reaches a real DB |
| 3a. Idempotent retry (same key) | `test_same_key_retried_creates_exactly_one_row_and_replays_response` | **FAILED** | Same — register never reaches a real DB |
| 3b. Missing Idempotency-Key | `test_missing_idempotency_key_is_rejected` | **FAILED** | Same — the test's own `_register` helper fails before the assertion under test even runs |
| 3c. Same key, two orgs | `test_same_key_across_two_orgs_does_not_collide` | **FAILED** | Same |
| 4. Financial-advice job via real Inngest | `test_financial_advice_job_completes_via_real_inngest` | **SKIPPED** | `pytest.mark.skipif` fired because `INNGEST_BASE_URL` (`http://localhost:8288`) is not reachable — by design this scenario is never simulated in-process, so "skipped with reason recorded" is the correct honest outcome here, not a failure to fix |
| 5a. Duplicate email registration | `test_duplicate_email_registration_is_rejected` | **FAILED** | register never reaches a real DB |
| 5b. Wrong password login | `test_login_with_wrong_password_is_rejected` | **FAILED** | Same |
| 5c. Unauthenticated request | `test_unauthenticated_request_to_protected_route_is_rejected` | **PASSED** | This scenario needs no DB/Redis at all — `AuthMiddleware` rejects a request with no bearer token purely in-process. Genuinely exercised and genuinely correct. |
| 5d. Malformed bearer token | `test_malformed_bearer_token_is_rejected` | **PASSED** | Same reasoning — JWT decode failure is local, no DB/Redis needed. Genuinely exercised and genuinely correct. |
| 5e. Non-positive sale amount | `test_non_positive_sale_amount_is_rejected` | **FAILED** | register (setup) never reaches a real DB |
| 5f. Non-positive expense amount | `test_non_positive_expense_amount_is_rejected` | **FAILED** | Same |

**Every single failure above is `httpx.ProxyError: 502 Bad Gateway`
(or the identical underlying `httpcore.ProxyError`) raised from
`repository/users_repository.get_user_by_email` / `create_user` while
talking to the configured `SUPABASE_URL`.** None of them are assertion
failures, import errors, or logic bugs in the test code itself — grep of
the full run log confirms every traceback bottoms out at the same
`ProxyError: 502 Bad Gateway` on the Supabase host. This is
**blocked: infra unreachable in this environment**, not a genuine
test/code failure.

The 2 passes are real, unconditional passes that happen to need no
external infra at all — they are not evidence the DB/Redis-dependent
scenarios work, only that the parts of the auth middleware that run
entirely in-process work.

## What this means for the task

- The test code in this folder is believed correct and ready to run as-is
  the moment real Supabase/Redis/Inngest credentials and a live dev server
  are available — swap `.env`'s placeholder values for real ones and rerun
  `python -m pytest tests/e2e/prompt-2 -v` (and set `INNGEST_BASE_URL` to a
  reachable dev server, running `docker compose up`, to unskip scenario 4).
- No result here has been faked, mocked, or backfilled to look green. The
  9 failures and 1 skip are reported as blocked-by-environment, honestly,
  with the exact connection errors captured above.
- The one accidental use of fakes (the repo-root autouse `_wire_fakes`
  fixture silently applying to this directory too) was caught and
  corrected in `conftest.py` before drawing any conclusion from a "passing"
  run — that first, undisclosed-fakes run is not reported as a real result
  anywhere in this document.
