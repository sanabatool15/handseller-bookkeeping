# Resilient Background Jobs (Inngest)

Implementation: `jobs/inngest_client.py`, `jobs/financial_agent_job.py`,
mounted into the app via `app/main.py`.

## What we did

The financial-advisor feature never runs synchronously inside an HTTP
request. Instead:

1. `POST /agent-jobs/financial-advice` (via `services/agent_job_service.py`)
   creates an `agent_jobs` row (`status="pending"`) and fires an
   `financial/advice.requested` Inngest event carrying `job_id` and
   `org_id`, then returns **`202 Accepted`** with the `job_id` immediately
   — the HTTP request never waits on the AI call.
2. `GET /agent-jobs/{job_id}` lets the client poll `agent_jobs.status`
   (`pending → processing → completed | failed`) and read the result once
   done.
3. `jobs/financial_agent_job.py` defines the actual workflow as an Inngest
   function with **three steps**, each wrapped in `step.run(step_id, fn)`:
   - **`gather-data`**: pulls this month's sales/expense totals via
     `services.financial_report_service.monthly_summary`.
   - **`run-agent`**: calls `agents.api.financial_advisor_agent.run_financial_advisor`;
     on **any** exception (network failure, missing API key, the `agents`
     package-shadowing issue — see `06-agents-layer.md`) it falls back to
     `agents.rules.fallback_engine.rule_based_financial_advice` instead of
     failing the job.
   - **`finalize`**: marks the job `completed` and stores the result.

   Each step writes an `agent_logs` row (`step_name`, `action_summary`,
   `insights_generated`) **and** updates `agent_jobs.status`/`current_step`
   via `repository/agent_jobs_repository.py`, in addition to whatever
   Inngest itself tracks internally.
4. An `on_failure_handler` is registered so that if all of Inngest's
   automatic retries (`retries=3`) are exhausted, the job is explicitly
   marked `failed` with `error_details` — it never just silently
   disappears from the user's perspective.

## Why we did it

Two problems drove this design:

1. **Blocking the request thread on an unreliable external call is a
   reliability bug.** Running the OpenAI Agents SDK call *inside* the
   FastAPI request handler for the financial-advice endpoint means a slow
   or failed OpenAI response leaves the HTTP client (and the server's
   request-handling thread/worker) blocked for the duration — for a
   financial-advice feature that can reasonably take several seconds of
   LLM reasoning, that's an unacceptable amount of time to hold open a
   synchronous HTTP request, and it doesn't degrade gracefully under load
   (more concurrent advice requests just means more blocked workers).

2. **A background job needs to survive a crash without repeating
   side-effecting or billable work.** If the process crashes or is
   restarted after step 1 (`gather-data`) succeeds but before step 2
   (`run-agent`, which costs a real OpenAI API call) completes, a naive
   "just retry the whole function" approach would re-run `gather-data`
   (harmless, but wasteful) and potentially call the paid LLM API again
   for a request that may have actually already gotten a response that was
   lost. Inngest's `step.run()` memoizes each step's result: on a retried
   invocation, already-completed steps are replayed from their memoized
   result instead of re-executed, so a crash after step 2 resumes at step 3
   without paying for step 2 again.

We deliberately **also** persist progress to `agent_jobs`/`agent_logs` in
Postgres on top of Inngest's own internal step memoization, rather than
relying on Inngest's internal state alone. This is because the rest of the
app (the polling endpoint, any future dashboard, the MCP `stream_job_logs`
tool) needs to query job status and history through the normal database
layer — it has no way to introspect Inngest's internal execution state
directly, and shouldn't need to.

## Why the agent step always falls back instead of failing the job

`_step_run_agent` catches `Exception` broadly and falls back to
`rule_based_financial_advice` rather than letting the step raise (which
would trigger an Inngest retry, and eventually `on_failure_handler`,
marking the whole job `failed`). This is deliberate: a bookkeeping user
asking for financial advice should get *some* useful, if simpler, answer
even if the OpenAI API is down, misconfigured, or the SDK is unreachable
due to the package-shadowing issue described in `06-agents-layer.md` — not
a failed job with no output at all. The `source` field
(`"openai_agent"` vs `"rule_based_fallback"`) in the stored result makes
which path was taken transparent, rather than silently pretending the
rule-based answer came from the LLM.

## Documented SDK-version assumption

This was built and verified against **`inngest==0.5.19`** by actually
installing it and inspecting the real API surface, rather than guessing
from documentation alone:

- `inngest.Inngest(app_id=..., event_key=..., signing_key=..., is_production=...)`
- `client.create_function(fn_id=..., name=..., trigger=inngest.TriggerEvent(event=...), retries=...)` → decorator
- Handler signature: `async def handler(ctx: inngest.Context)` — a single
  argument; there is no separate `step` parameter. Step methods are called
  via `ctx.step` (`Context` is a dataclass whose `step` field holds them).
- `ctx.step.run(step_id, async_callable)` — memoized
- `inngest.fast_api.serve(app, client, functions, serve_path="/api/inngest")` —
  mounts the routes Inngest's dev server / cloud needs to call into

If you upgrade the `inngest` package and something breaks, **only
`jobs/inngest_client.py` and `jobs/financial_agent_job.py` should need
changes** — this isolation was intentional so a dependency bump has a
narrow blast radius. Re-verify the actual installed API shape (don't just
assume the snippet above still holds) before changing these files after an
upgrade.

## Known gap: no idempotency protection on the Inngest event itself

The HTTP-level idempotency middleware (`04-idempotency-redis.md`) only
guards the initial `POST /agent-jobs/financial-advice` request — it
deduplicates repeated *HTTP* calls with the same `Idempotency-Key`. It does
**not** protect the Inngest event that request fires. If the same
`financial/advice.requested` event is delivered twice — an Inngest retry, a
duplicate webhook delivery, or any other at-least-once delivery scenario —
nothing today stops the function from creating a second `agent_jobs` row or
re-running the agent (including a second, billable OpenAI call) for what
is effectively the same request.

This is a real, currently-unaddressed gap, not a hypothetical: Inngest's
delivery model is at-least-once, so duplicate event delivery is an expected
occurrence in production, not an edge case. A fix needs either an
idempotency key set on the Inngest event itself (many Inngest SDKs support
an `id`/dedupe key at the trigger level) or a uniqueness check (e.g. against
the originating `job_id` or HTTP idempotency key) before
`gather-data`/`run-agent` create or mutate an `agent_jobs` row. This is
intentionally left undone here — documented as a known gap for a future
fix, not silently patched.

## Where this is tested

`tests/unit/test_fallback_engine.py` exercises the rule-based fallback path
directly. `tests/e2e/test_full_inngest_workflow.py` covers the real
end-to-end flow but requires a live `docker compose up` stack (a real
Inngest dev server actually invoking the function) and is gated behind
`RUN_E2E=1` — see `09-testing-strategy.md` for why this isn't run by
default.
