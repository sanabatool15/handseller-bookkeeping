# Database Schema

Full SQL lives in `sql/schema.sql`. This doc explains what each table is for
and why it's shaped the way it is; read it alongside the SQL file rather
than as a substitute for it.

## Tables

### `orgs`
The tenant boundary of the whole system. `owner_id` points at the `users`
row that owns the org. Every other business-data table (`sales`,
`expenses`, `agent_jobs`) hangs off `org_id`, because **org, not user, is
the unit of tenant isolation** — multiple users can belong to one org (a
handseller business with several staff), and all of them see the same
ledger.

### `users`
`org_id` (nullable at the column level, but always populated by the time a
user can log in) ties a user to exactly one org. `hashed_password` stores a
PBKDF2-HMAC-SHA256 hash (see `03-multi-tenancy-security.md` and
`10-known-limitations.md` for why not bcrypt). `role` exists for future
use (owner/admin/member) but isn't yet enforced anywhere beyond org
membership — see limitations doc.

There's a circular FK here on purpose: `orgs.owner_id` references
`users.id`, and `users.org_id` references `orgs.id`. The
`fk_orgs_owner` constraint is added via `alter table` *after* both tables
exist, and is `deferrable initially deferred` specifically so a single
transaction can insert the first user and their org together without a
chicken-and-egg FK violation (create the org with a placeholder, create the
user referencing it, then the deferred constraint is checked at commit).

### `sales` / `expenses`
The actual bookkeeping ledger. Both carry `org_id` (tenant scope),
`created_by` (which user logged it — for audit trail, not authorization),
`amount`, `category` (free-text, used for expense-breakdown analytics in
earlier ladder steps and still present here), and a date column
(`sale_date` / `expense_date`) distinct from `created_at` — the date the
transaction happened on the ground can differ from when it was entered
into the system (e.g. entering yesterday's cash sales this morning).
`expenses` additionally has `voucher_reference` (a receipt/document
pointer), which was a specific requirement from the ladder's schema step.

`idx_sales_org_id` / `idx_expenses_org_id`: since **every single query**
against these tables filters by `org_id` (see
`03-multi-tenancy-security.md`), an index on that column is not optional —
without it, every scoped query becomes a full table scan as the ledger
grows across many tenants.

### `agent_jobs`
Tracks the lifecycle of an asynchronous AI task (see
`05-background-jobs-inngest.md`). `status` is one of
`pending → processing → completed | failed`. `current_step` records which
Inngest step last completed, `result` holds the final output, and
`error_details` is populated only on `failed` (by the Inngest
`on_failure` handler once retries are exhausted). This table is what a
polling `GET /agent-jobs/{job_id}` endpoint reads — it exists so job state
is visible to the rest of the app independent of Inngest's own internal
step-memoization state, which the app doesn't have direct query access to.

### `agent_logs`
A step-by-step audit trail for each `agent_jobs` row: one row per
completed step (`gather_data`, `run_agent`, `finalize`), each with a
human-readable `action_summary` and a structured `insights_generated` jsonb
blob. This is what lets `mcp_gateway/server.py`'s `stream_job_logs` tool replay a
job's history to an external MCP client, and it's the audit trail that
proves — after the fact — exactly what data the AI agent saw and what it
concluded, which matters for a bookkeeping system where "why did the agent
say this" needs an answer.

## `updated_at` trigger pattern

Every table gets an identical `before update ... execute function
set_updated_at()` trigger, backed by one shared `set_updated_at()`
function defined once at the top of the schema. If you add a new table,
follow this exact pattern (define the column, add the trigger) rather than
inventing a new mechanism — consistency here means one place to look for
"how does `updated_at` get maintained" across the whole schema.

## Row Level Security (RLS) — defense in depth, not the primary control

`sales`, `expenses`, `agent_jobs` (and, via policy, effectively
`agent_logs` by extension through `agent_jobs`) have RLS enabled with a
policy that checks `org_id = current_setting('app.current_org_id', true)::uuid`.

**This is deliberately a second layer, not the primary defense.** The
primary tenant-isolation control is the application-layer rule in
`repository/*.py` (every query scoped by `id`+`org_id` — see
`03-multi-tenancy-security.md`), because:

1. The app currently connects to Supabase using a service-role key (see
   `.env.example`'s `SUPABASE_SERVICE_KEY`), which **bypasses RLS
   entirely** by design (service-role is meant for trusted backend code).
   So today, RLS provides no runtime protection against the app's own
   bugs — it only protects against someone querying the database directly
   with a non-service-role credential, or a future migration to
   client-side/anon-key access patterns.
2. `current_setting('app.current_org_id', true)` requires something in the
   connection to actually `SET app.current_org_id = '...'` per request —
   this app does not currently do that (see `10-known-limitations.md`).

RLS is included because it's cheap, standard Supabase practice, and free
insurance if the connection strategy ever changes — but do not treat it as
the reason cross-tenant access is prevented in this system today. That job
belongs entirely to `repository/*.py` and is verified by
`tests/integration/test_sales_multitenancy.py` and
`tests/unit/test_ownership.py`.

## Applying the schema

```bash
supabase db push --file sql/schema.sql
```

or paste it into the Supabase SQL editor. It's written to be idempotent for
tables (`create table if not exists`) but **not** for triggers/policies —
re-running it against a database that already has them will error on
duplicate trigger/policy names. If you need a truly re-runnable migration
setup, that's a good next investment (see `10-known-limitations.md`), not
something silently "fixed" by wrapping everything in `if not exists` when
it's applied.
