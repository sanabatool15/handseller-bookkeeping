# Multi-Tenancy & Structural Security

## What we did

Every repository function that reads, updates, or deletes a *specific* row
filters by **both** `id` and `org_id` in the same database call:

```python
db.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).execute()
```

There is no code path anywhere in this codebase that fetches a row by `id`
alone and separately compares its `org_id` afterward in Python.

`repository/base.py` additionally exposes a shared helper:

```python
def get_ownership(db: Client, *, table: str, record_id: str, org_id: str) -> bool:
    resp = db.table(table).select("id").eq("id", record_id).eq("org_id", org_id).limit(1).execute()
    return bool(resp.data)
```

used by services that need a yes/no ownership check without needing the
full row (e.g. before enqueuing a background job tied to a record).

When a scoped query returns zero rows — because the id doesn't exist *or*
because it belongs to a different org — the service layer raises a
**404 Not Found**, never a 403. A different org's record existing is not
information this API discloses.

## Why we did it

This is the single most important guarantee in the system, because it
closes a real vulnerability class: "check-then-fetch" (also called IDOR —
Insecure Direct Object Reference), where a record is fetched by `id` alone
and its `org_id` is compared *afterward* in application code. That pattern
is a vulnerability waiting to happen, because the fetch and the check are
two separate steps — any future refactor, a missed code path, or a new
endpoint that copies 90% of an existing handler and drops the check can
produce a query with no `org_id` filter at all, returning another tenant's
data.

By baking `org_id` into the exact same query as the `id` filter, the
vulnerability becomes **structurally impossible**, not just
"unlikely because we remembered to check." There is no way to write a
repository function that returns another org's row for a given id, because
the query that would do that simply returns nothing.

## Why 404, not 403

Returning `403 Forbidden` for a record that belongs to another org
confirms to the caller that a record with that `id` *exists* somewhere —
just not for them. For a bookkeeping system, that's real information
leakage (e.g. it would let one org enumerate whether specific sale/expense
IDs exist across the whole platform, or infer the target's data volume by
probing IDs). Returning `404 Not Found` — indistinguishable from "this id
was never a real record" — leaks nothing. This system standardizes on
that: cross-tenant access to an existing-but-foreign record and access to a
genuinely nonexistent record produce the exact same response.

## Where this is tested

- `tests/unit/test_ownership.py` — unit-level check on `get_ownership()`
  and the scoped-query pattern using the in-memory fake Supabase client.
- `tests/integration/test_sales_multitenancy.py` — end-to-end through
  `TestClient`: creates a sale for org A, then confirms org B gets 404 on
  read, update, and delete by the exact same id.

If you change anything in `repository/*.py`, **re-run these two test files
first.** If a cross-tenant request starts returning `200` (data leak) or
`403` (existence leak) instead of `404`, you have reintroduced exactly the
bug this whole ladder step was built to eliminate — treat that as a
release-blocking regression, not a minor test failure to silence.

## What this does NOT cover (see `10-known-limitations.md` for detail)

- **Row-level Postgres RLS is not the enforcement mechanism here** — the
  app connects with a service-role key that bypasses RLS, and nothing sets
  `app.current_org_id` per-connection today. RLS is present as defense in
  depth (see `02-database-schema.md`), but the actual guarantee comes from
  every repository query being scoped in application code, verified by the
  tests above.
- **Role-based permissions within an org** (owner vs. member) are not yet
  enforced — any authenticated user in an org can read/write all of that
  org's sales and expenses. The `users.role` column exists for this future
  use but nothing currently branches on it.
