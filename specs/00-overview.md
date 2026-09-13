# Overview

This directory documents, in detail, every major thing built in this
(`variant-5`) implementation of the handseller bookkeeping backend, and the
reasoning behind each decision. It exists because this branch is the one
earmarked for real production iteration — future changes (by a human or an
AI agent) should understand *why* something was built a certain way before
changing it, not just *what* the code does.

Read `CLAUDE.md` at the repo root first — it has the hard rules and the
per-subsystem "before you touch X" checklist. These `specs/*.md` files go
deeper on the reasoning behind each subsystem.

## Why this system exists in this shape

This backend is the final step of a 5-step "prompt ladder" exercise: each
prior version (`variant-1` .. `variant-4` in this repo, kept only for
comparison) added one more constraint after a concrete failure was observed
in the previous version. The shape of this codebase is a direct response to
those failures, not an arbitrary design:

1. **variant-1** (no architecture) → mixed HTTP/business/DB logic in one
   file, wrong domain model, no security.
2. **variant-2** (3-tier architecture + JWT) → clean layering, but
   authorization was "fetch by id, then compare org_id" (check-then-fetch) —
   a data-leak risk.
3. **variant-3** (explicit schema + ownership function) → fixed schema
   accuracy, added a dedicated ownership check, but it was still a separate
   round-trip from the fetch, not baked into the query.
4. **variant-4** (structural id+org_id scoped queries + agents/MCP +
   DB-table idempotency) → tenant isolation became airtight, but the
   idempotency store was a synchronous Postgres write on every mutating
   request, and the AI agent ran inline in the HTTP handler, blocking on a
   slow/unreliable OpenAI call.
5. **variant-5 (this branch)** → replaced the Postgres idempotency table
   with Redis, moved agent execution into an asynchronous, crash-resumable
   Inngest job, and added a full FastMCP server so external LLM clients can
   use the same ledger.

Every design decision in the specs below traces back to one of these
concrete, observed problems — not a hypothetical "best practice."

## Spec index

- [`01-architecture-layering.md`](./01-architecture-layering.md) — the
  routers/services/repository split and why it's non-negotiable.
- [`02-database-schema.md`](./02-database-schema.md) — every table, why it
  exists, and the RLS-as-defense-in-depth strategy.
- [`03-multi-tenancy-security.md`](./03-multi-tenancy-security.md) — the
  structural id+org_id scoping rule that eliminates check-then-fetch, and
  why 404 (not 403) is the correct response for cross-tenant access.
- [`04-idempotency-redis.md`](./04-idempotency-redis.md) — the Redis-backed
  idempotency middleware, why it replaced a database table, and the
  concurrency lock that prevents duplicate writes on parallel retries.
- [`05-background-jobs-inngest.md`](./05-background-jobs-inngest.md) — why
  agent work moved off the request thread, how the multi-step Inngest job
  is structured, and how it survives a mid-run crash.
- [`06-agents-layer.md`](./06-agents-layer.md) — the `agents/` package
  structure (prompts/api/rules/tools), the OpenAI Agents SDK integration,
  the deterministic rule-based fallback, and the `agents` package-name
  collision.
- [`07-mcp-server.md`](./07-mcp-server.md) — the FastMCP stdio server and
  how each of the 5 MCP primitives (tools, resources, prompts, sampling,
  logging) was implemented, plus the `mcp` package-name collision.
- [`08-infrastructure-docker.md`](./08-infrastructure-docker.md) — the
  Dockerfile and docker-compose topology and why it's shaped this way.
- [`09-testing-strategy.md`](./09-testing-strategy.md) — the unit /
  integration / e2e split, the fake Supabase client and `fakeredis`, and why
  the e2e suite is gated behind `RUN_E2E=1` instead of always running.
- [`10-known-limitations.md`](./10-known-limitations.md) — the honest,
  currently-unfixed gaps (Redis failure isn't a graceful degrade; MCP
  sampling/logging aren't exercised against a live external client; CORS is
  wide open for local dev) so they don't get silently rediscovered later.
