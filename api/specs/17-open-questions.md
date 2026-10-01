# Open questions (SQL Server migration)

1. **OUTPUT INSERTED.* vs triggers.** Why unsure: the brief says `OUTPUT INSERTED.*`, but tables with
   enabled triggers reject OUTPUT without INTO (error 334) and every table gets an updated_at trigger.
   Assumed: use `OUTPUT ... INTO @table` + SELECT everywhere (see spec 13). Alternative: drop triggers
   and set `updated_at` in UPDATE statements. Later slices need to know.
2. **Email case sensitivity.** Postgres `users.email` was case-sensitive; SQL Server's default collation is
   case-insensitive, so `A@x.com` and `a@x.com` now collide. Assumed this is desirable; emails are not lower-cased by the app.
3. **Register is one transaction, owned by the service via `repository.base.transaction`.** The `get_sql_db`
   dependency would also commit at request end; assumed explicit transaction in the service is clearer and
   keeps atomicity independent of how the Db was obtained.
4. **`updated_at` returned from `set_user_org` is pre-trigger** (OUTPUT INTO captures INSERTED before the AFTER trigger fires). Assumed harmless.
5. **Unrun T-SQL / datetimeoffset converter.** The pyodbc output converter for type -155 (`datetimeoffset`) is from
   known pyodbc recipes but untested here.
6. **`pyodbc` in `requirements.txt` / Vercel.** Added to requirements and pyproject; the Vercel deployment (spec 12) has
   no Microsoft ODBC driver, so the API cannot reach SQL Server from there. Assumed local `uvicorn` is the target now.
7. **`get_ownership` in `repository/base.py`** was the Supabase version with a separate `get_ownership_sql`. *(Resolved in F0b: `get_ownership` is now the SQL version, allow-listed tables, `get_ownership_sql` removed.)*
8. **mcp_gateway/server.py** read `agent_logs` through Supabase directly. *(Resolved in F0b: `agent_jobs_repository.list_logs_for_job` via `agent_job_service.get_job_logs`.)*

## Added in slice F0b

9. **`agent_logs.org_id` is a schema addition.** Why unsure: the brief says "port of schema.sql", which has no `org_id` on
   `agent_logs`; but the project rule (static guard) wants `org_id` in every tenant-table statement. Assumed: add the column
   (NOT NULL), a composite FK `(job_id, org_id)` -> `agent_jobs(id, org_id)` and `idx_agent_logs_org_id`; `add_log`/`get_completed_steps`
   therefore gained an `org_id` parameter (all callers updated). If you have existing Postgres data, an import must fill `org_id` from the job.
10. **No `UNIQUE (job_id, step_name)` on `agent_logs`.** Why unsure: Inngest memoizes steps, but if a step body commits its log and
    Inngest then fails to record the step result, the retry re-runs the body and would insert the same `(job_id, step_name)` again; a
    UNIQUE index would turn that into a permanently failing job. Assumed: duplicates are tolerated (`get_completed_steps` returns a set).
    A safe version needs an idempotent `add_log` (`IF NOT EXISTS`/`MERGE`) first.
11. **Type/length choices.** `category` nvarchar(100), `customer_name` nvarchar(200), `voucher_reference` nvarchar(200), `job_name`/`step_name`/`current_step`
    nvarchar(100), `description`/JSON columns nvarchar(max). Postgres `text` was unbounded, so an over-long category/name now fails with
    SQL Server error 8152 (HTTP 500) instead of being stored. No length validation exists in the API yet. Assumed acceptable.
12. **`agent_jobs.status` CHECK** (pending/processing/completed/failed) is new; the code only ever writes those four. Assumed fine.
13. **No `ON DELETE CASCADE`** (except `agent_logs -> agent_jobs`) because SQL Server rejects multiple cascade paths. Postgres cascaded
    org deletion to everything; the app never deletes orgs/users, but the e2e cleanup helper (`tests/e2e/e2e_db.py::purge_org`) deletes children explicitly.
14. **Unrun T-SQL, new bits:** `INSERT ... OUTPUT ... INTO @o SELECT ... FROM agent_jobs WHERE id = ? AND org_id = ?` with `?` in the select list,
    `COALESCE(?, col)` with NULL parameters, `ORDER BY ... OFFSET ? ROWS FETCH NEXT ? ROWS ONLY` with bound parameters, composite FK + UNIQUE (id, org_id),
    `CONVERT(date, SYSUTCDATETIME())` as a column default. All standard T-SQL, but not executed here.
15. **`OUTPUT ... INTO @o` returns the pre-trigger `updated_at`** for UPDATEs (same as F0a #4): `PUT /sales/{id}` and job status updates show the old
    `updated_at` in that response; a later GET shows the bumped value.
16. **Job step holds one connection across the LLM call** (`_step_run_agent`). Record tools write through the same connection and commit when the step
    ends; on agent failure the step rolls back those writes before falling back. Assumed better than committing partial agent writes; the old Supabase code autocommitted each write.
17. **Dates in "this month".** Jobs/MCP use `datetime.utcnow()` for the month and sale/expense dates are now UTC "today" (they used the server's local date before). Assumed UTC is the intended business timezone.
18. **`/health` JSON changed:** `checks.supabase` -> `checks.database`. Top-level `status` stays `"ok"` (the Dockerfile HEALTHCHECK ignores the body anyway). Startup only logs a warning if SQL Server is down (it used to "fail fast" only on client construction, which never touched the network).
19. **Pre-existing: `hashed_password` is returned** in `/auth/register` and `/auth/login` `user` objects (rows are returned as-is, shape unchanged by the port as requested). That is a security smell; not fixed here to keep the JSON shape. Also `lib/types.ts` types `AgentJob.error_details` as `string` but the API returns a dict.
20. **e2e suites (tests/e2e/prompt-2..5, test_full_inngest_workflow.py):** conftests/helpers were ported to SQL (`tests/e2e/e2e_db.py`) but never run against a real SQL Server/Redis/Inngest. prompt-2/3 are not RUN_E2E-gated (they error out without infra, as before); prompt-4/5 are gated. `tests/e2e/prompt-N/*.md` result/scenario docs still describe Supabase runs (historical). The Dockerfile/docker-compose were deliberately not touched (no Docker work in this migration), so `docker compose up` has no SQL Server and no ODBC driver in the image.
21. **`api/sql/schema.sql` kept** as the legacy Postgres reference (not deleted); nothing reads it.
22. **Pre-existing test bug fixed:** `tests/e2e/prompt-1/test_financial_advice_job_journey.py` called `_step_run_agent` with a stale signature (failing before F0b); it now passes `requested_by`/`question` and forces the rule-based fallback.

## Added in slice F1 (products & stock)

23. **`reason` on adjust-stock is not persisted.** Why unsure: the brief asks for `reason: str|null` but only the `products` table exists. Assumed: validate (<= 500 chars) and ignore until a `stock_movements` table (audit trail) is added in a later slice.
24. **Hard DELETE of products.** Why unsure: once sales/line items reference products, a hard delete would orphan or violate FKs. Assumed: fine for now (no references exist); `is_active` is there for a future soft-delete switch.
25. **Quantity cap of 1,000,000** (initial stock, delta, reorder level) is my choice, to prevent int overflow in `stock_qty + delta`. Adjust if the business needs bigger numbers (then widen the column to bigint).
26. **SKU uniqueness is case-insensitive** (default SQL Server collation) and whitespace is trimmed by the service, so `abc` and `ABC ` collide. Assumed desirable.
27. **`low_stock` = `stock_qty <= reorder_level`**, applied to inactive products too. Assumed acceptable.
28. **Stock/price edits via `PUT`:** `PUT` cannot change `stock_qty` (use adjust-stock) and cannot set a column to NULL (same COALESCE convention as sales). `is_active=false` is accepted but nothing filters on it yet.
29. **`updated_at` is pre-trigger in the OUTPUT row** of PUT/adjust-stock responses (same as #4/#15); a later GET shows the bumped value.
30. **Unrun T-SQL, new bits:** `UPDATE ... SET stock_qty = stock_qty + ? OUTPUT ... INTO @o WHERE id = ? AND org_id = ? AND stock_qty + ? >= 0` with the delta bound twice as int parameters; inline `CHECK` on a column that also has a `DEFAULT` constraint; `bit` returned by pyodbc as Python bool (the tests accept True/1).
