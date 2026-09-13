# Idempotency Middleware (Redis-backed)

Implementation: `middleware/idempotency.py`.

## What we did

Every mutating request (`POST`, `PUT`, `PATCH`) must carry an
`Idempotency-Key` header, enforced by middleware that runs **before** any
router handler:

- **Missing key** → `400 Bad Request` immediately.
- **First time seeing this key** (cache miss) → acquire a short-lived Redis
  lock (`SET NX EX 30`), run the request normally, capture the response
  status code + JSON body, cache it in Redis for `IDEMPOTENCY_TTL_SECONDS`
  (default 24h, from `.env`), release the lock, return the response.
- **Repeat request with the same key** (cache hit) → return the cached
  status code + body immediately, without re-running the handler or
  touching the database again.
- **Two concurrent requests with the same key racing each other** → the
  loser (the one that doesn't get the lock) gets `409 Conflict` instead of
  both executing the handler and double-processing a sale/expense.

Cache keys are scoped **per-org**: `idempotency:{org_id}:{key}`, taken from
`request.state.user.org_id` (populated by `AuthMiddleware`, which
therefore must run before this middleware — see the ordering note below).
Before authentication exists (e.g. `/auth/register`), the scope falls back
to `"anon"`. Auth endpoints themselves (`/auth/login`, `/auth/register`)
and the Inngest webhook path (`/api/inngest`) are explicitly exempted from
requiring the header.

Error responses (`>= 500`) are **never cached** — a transient server error
shouldn't get "stuck" as the permanent cached answer for that idempotency
key; the client is expected to retry with the same key and get a fresh
attempt.

## Why we did it

Two things drove this design, both traced to a concrete problem in an
earlier version of this project:

1. **Duplicate submissions are a real bookkeeping bug, not a hypothetical.**
   A handseller on a flaky mobile connection retrying a "log this sale"
   POST after a timeout must not end up with the same sale recorded twice
   — that directly corrupts the books. Some verification mechanism against
   retried requests was always going to be required.

2. **`variant-3`'s first attempt at solving this used row-level database
   locks inside synchronous endpoint handlers** to prevent duplicate writes.
   This caused real connection/latency problems: a lock held inside a
   request handler ties up a database connection for the request's full
   duration, and under retries (the exact scenario this was meant to
   handle) that turns into lock contention and connection-pool starvation —
   the fix made concurrent request handling *worse*, not better.

3. **`variant-4`'s next attempt moved to an `idempotency_keys` Postgres
   table** (insert-with-unique-constraint per request). This correctly
   avoided row locks, but still put a synchronous database round-trip
   (an INSERT, hitting a UNIQUE constraint on retries) on the hot path of
   every single mutating request — including ones that aren't being
   retried at all. Every `POST /sales` paid a DB-write cost purely for
   deduplication bookkeeping.

Redis solves both problems: it's an in-memory key-value store built
exactly for this kind of high-frequency, short-TTL, read-heavy-on-repeat
workload. A cache hit/miss check is a single fast Redis round-trip instead
of a Postgres write, and the `SET NX` lock primitive gives us safe
concurrent-request handling without holding a database row lock at all.

## Why the lock (`SET NX EX 30`) in addition to the cache

A cache-only design (check Redis, if miss run the handler, then write to
Redis) has a race: two requests with the same key can both miss the cache
simultaneously (e.g. a client that fires the same request twice in
parallel by mistake, or a proxy retry racing the original) and both
proceed to run the handler, defeating the entire point of idempotency. The
lock closes this: only one request can hold `idempotency-lock:{org}:{key}`
at a time, so the second one fails fast with `409` instead of silently
double-executing.

## Why the middleware runs where it does

`app/main.py` adds `IdempotencyMiddleware` before `AuthMiddleware`
(Starlette runs middleware in reverse-registration order, so the one added
last runs first). This means **Auth runs first**, populating
`request.state.user`, which Idempotency then reads to scope its cache key
per-org. If you ever reorder middleware registration in `app/main.py`,
this dependency breaks silently (idempotency keys would fall back to the
`"anon"` scope for authenticated requests too) — re-check
`tests/integration/test_idempotency.py` after any middleware reordering.

## Where this is tested

`tests/integration/test_idempotency.py`, using `fakeredis` (an in-memory
Redis-compatible fake) so tests run with no real Redis instance required.
Covers: missing-header 400, cache-hit replay returning the identical
response without re-invoking the handler, and per-org scoping (same key,
different orgs, don't collide).

## What this does NOT cover (see `10-known-limitations.md`)

If Redis itself is unreachable, `get_redis()` calls in the middleware will
raise, and — because there's no explicit try/except around them today —
that surfaces as an unhandled exception, caught by `app/main.py`'s generic
exception handler, which returns a generic `500`. There is currently no
graceful "Redis is down, process the request anyway and skip
deduplication, just log a warning" fallback path. This is a known,
documented gap, not an oversight to silently work around — see
`10-known-limitations.md` before deciding how to fix it (a
naive try/except could reintroduce duplicate-processing risk if done
carelessly).
