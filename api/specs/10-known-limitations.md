# Known Limitations (Honest, As-Built)

This file exists so real gaps don't get silently rediscovered later, or
mistaken for oversights when they were actually deliberate scope decisions
made explicit at build time. If you fix one of these, update this file
rather than deleting the entry — leave a note on what changed and when.

## 1. Redis failure is not a graceful degrade

`middleware/idempotency.py` calls `get_redis()` and awaits Redis commands
with no try/except around them. If Redis is unreachable (network blip,
Redis container down, wrong `REDIS_URL`), the middleware raises, which
bubbles up to `app/main.py`'s catch-all exception handler and returns a
generic `500` to the caller — for **every** mutating request, since every
`POST`/`PUT`/`PATCH` goes through this middleware.

**Why this wasn't fixed as part of this build:** a naive fix (wrap in
try/except, log a warning, proceed to call the handler anyway) would
silently defeat the entire idempotency guarantee during a Redis outage —
duplicate requests would be processed as if they were unique, which for a
bookkeeping ledger (double-counted sales/expenses) may be worse than a
visible `500`. A correct fix needs a real decision: e.g. a circuit breaker
that fails closed (current behavior) vs. fails open (process anyway,
accept duplicate risk, surface a warning/metric) vs. a short local retry
before giving up. That's a product/reliability tradeoff, not a one-line
patch — don't "fix" this with a bare try/except without deciding which
failure mode you actually want.

## 2. MCP Sampling and Logging primitives aren't exercised end-to-end

`summarize_ledger_via_client_llm` (sampling) and the logging calls
(`ctx.log`/`ctx.error`) throughout `mcp_gateway/server.py` are implemented against
the documented `fastmcp`/MCP protocol shape and covered by
`tests/unit/test_mcp_server.py` for correct *registration* — but both are
inherently interactive, client-driven features (a real connected MCP
client must support and respond to `sampling/createMessage`; log
notifications need a client actually listening on its log stream). They
were not verified against a live external client (e.g. Claude Desktop)
inside this sandboxed build environment. **Before relying on these in
production, connect a real MCP client and manually verify** both the
sampling round-trip and that log notifications actually appear in the
client's UI.

## 3. CORS is wide open (`allow_origins=["*"]`)

`app/main.py` currently allows all origins with credentials. This is fine
for local development and was flagged explicitly in the original
Production Readiness Review pass as a **must-fix-before-production** item,
not something already handled. Before any real deployment, restrict this
to the actual frontend origin(s).

## 4. No role-based permissions within an org

`users.role` (owner/admin/member) exists as a column in `sql/schema.sql`
but nothing in `services/`/`repository/` currently branches on it. Any
authenticated user belonging to an org can read and write all of that
org's sales, expenses, and trigger agent jobs — there's no "member can log
sales but not view the full financial report" style restriction. The
tenant boundary (org vs. org) is airtight; the boundary *within* an org is
not yet implemented.

## 5. RLS policies aren't the actual enforcement mechanism today

As detailed in `02-database-schema.md` and `03-multi-tenancy-security.md`:
the app connects to Supabase with a service-role key, which bypasses RLS
entirely, and nothing in the app currently issues
`SET app.current_org_id = '...'` per connection/request for the RLS
policies to key off of. RLS is present as defense-in-depth / future-proofing
only. If you want RLS to be a *real* second line of defense (e.g. in case
of a future bug in `repository/*.py`, or a future code path that queries
Supabase directly with a non-service-role key), you need to (a) actually
set `app.current_org_id` per request/transaction, and (b) verify the
policies behave correctly under that setup — this hasn't been built or
tested here.

## 6. `sql/schema.sql` is not a re-runnable migration

Tables use `create table if not exists` (safe to re-run), but the
`updated_at` triggers and RLS policies do not use equivalent guards —
re-applying the full script against a database that already has them will
error on duplicate trigger/policy names. There's currently no migration
tool (Alembic, Supabase migrations, etc.) wired up; this is a single
apply-once script. If this system grows past its current schema, invest in
real migration tooling rather than hand-editing this file and hoping
nobody re-runs the old version.

## 7. Password hashing is hand-rolled, not a vetted library

`app/security.py` (or wherever password hashing lives) uses
PBKDF200,000-iteration HMAC-SHA256 with a random salt, implemented
directly rather than via `bcrypt`/`passlib`, specifically because no such
dependency was in the original task's dependency list. This is a
reasonable, correctly-implemented approach (constant-time comparison via
`hmac.compare_digest`, per-user random salt), but if you add a real
password-hashing library later, you must handle migration deliberately —
existing stored hashes will not verify against a different scheme's
verifier, so a flag-day cutover would lock out every existing user. Plan a
dual-scheme verify-then-upgrade migration if/when this changes.

## 8. Inngest and FastMCP integration assumptions are version-pinned observations, not guarantees

Both `jobs/inngest_client.py`/`jobs/financial_agent_job.py` (verified
against `inngest==0.5.19`) and `mcp_gateway/server.py` (verified against
`fastmcp==4.0.3`) document the exact API shapes they were built and tested
against by actually installing those versions and inspecting real
signatures — not guessed from documentation. If you upgrade either
dependency, **do not assume the documented shape still holds** — re-verify
against the newly installed version before trusting existing code (or this
spec's description of it) to still be accurate. See
`05-background-jobs-inngest.md` and `07-mcp-server.md` for the exact
assumptions recorded.

## 9. `record_agent` is only reachable via the planner's `handoff()`, and no production caller currently routes there

This is not a missing-endpoint gap — `record_agent` doesn't need its own
direct endpoint any more than `investigate_agent` does; both are reached
the same way, through the planner's `handoff()` in
`ai_agents/api/financial_advisor_agent.py`. The real, narrower gap is that
the only production caller of the agent chain, `run_financial_advisor()`
(called from `jobs/financial_agent_job.py:63`), always synthesizes a fixed
investigation-style question before invoking `run_bookkeeping_agent()` —
so in production the planner is never given an input that could
plausibly route to `record_agent`. `record_agent` and its mutating tools
(`create_expense_record`, `create_sales_record`, `deep_link`) are fully
implemented and prompted, and are exercised by
`tests/unit/test_financial_advisor_agent.py` and
`tests/e2e/prompt-4/`, `tests/e2e/prompt-5/` — but no live caller currently
passes a free-form `user_message` that would let the planner exercise that
handoff branch outside of tests.
