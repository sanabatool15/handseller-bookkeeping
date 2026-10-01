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

## Added in slice F2 (customers)

31. **Delete customer with sales = 409** (not detach). Why unsure: the brief allowed either. Assumed 409 is safer (no silent rewrite of sales, single atomic
    statement). Consequence: the user must unlink sales first (PUT sale `customer_id: null`); if you prefer detach-on-delete, change `_DELETE` to a two-statement transaction.
32. **Composite FK `(customer_id, org_id) -> customers(id, org_id)`** instead of a plain FK to `customers(id)`. Why unsure: the brief said FK to customers(id); the composite also gives DB-level tenant integrity,
    needs the extra `UQ_customers_id_org`, and is unrun T-SQL (same pattern as `agent_logs`).
33. **Filtered unique index needs SET options** (QUOTED_IDENTIFIER ON, ANSI_NULLS ON, ...) on every writing connection; pyodbc's defaults satisfy that, but a client that turns QUOTED_IDENTIFIER OFF would get error 1934. Unverified here.
34. **`CASE WHEN ? = 1 THEN ? ELSE col END` with bound parameters** (customers update; `CAST(? AS uniqueidentifier)` in sales update) is unrun T-SQL; pyodbc binds the flag as int and NULL as an untyped null. If SSMS/pyodbc complains about type inference, add explicit `CAST(? AS nvarchar(n))`.
35. **A sale created for a customer that is deleted a moment later** (race between the ownership check and the INSERT) fails on the FK (547) and surfaces as HTTP 500, not 404. Assumed rare enough; map 547 -> 404/409 if it matters.
36. **Email validation is deliberately minimal** (contains `@`, no whitespace, <= 320). Phones are free text (<= 32), compared case-insensitively and exactly (`+49 170` and `+49170` are different customers).
37. **`PUT /sales` behaviour change**: the router now passes only the fields the client sent (`exclude_unset`). Explicit `null` for amount/category/description/customer_name is still ignored as before; only `customer_id: null` means "unlink".
38. **Search is prefix-only** (`q%`), not contains, so it can use an index later; the UI searches server-side (250 ms debounce, limit 200). Switch to `%q%` if substring matching is wanted (escaping already handles it).
39. **`updated_at` in PUT customer responses is pre-trigger** (same as #4/#15/#29).

## Added in slice F3 (sale items, cash, procedures)

40. **Editing the amount of a QUICK sale does not touch the cash ledger.** Why unsure: item sales reject amount edits (422), but quick sales (no items) must keep accepting them for old clients. Assumed: balance/ledger stay as posted; void reverses what was posted (not the edited amount), so balance == ledger sum still holds. A later slice could post an `adjustment` entry for the delta.
41. **Deleting a product that was sold fails with the FK (547) => HTTP 500.** Why unsure: F1 delete is a plain `DELETE`; now `sale_items` references products. Assumed acceptable until a soft delete (`is_active`) or a 409 mapping is added (same pattern as customers).
42. **Procedures report business failures through OUTPUT parameters instead of THROW.** Why unsure: the brief said "THROW/ROLLBACK everything". With `XACT_ABORT ON` a THROW dooms the transaction (-1) and forces a FULL rollback, which would also roll back the API connection's own transaction when nested. Assumed the OUTPUT style (savepoint rollback, caller's work survives) is the safer textbook choice. Engine errors still go through CATCH.
43. **Nested vs own transaction.** The API connection is pyodbc autocommit OFF (implicit transactions) and the service often reads before calling the procedure, so the procedure usually runs NESTED (savepoint, no COMMIT; `get_db` commits at the end). Called directly from SSMS it owns the transaction and commits. Assumed this dual mode is right; see specs/15. Unverified on a real server.
44. **`@items` JSON parsing**: `OPENJSON(@items) CROSS APPLY OPENJSON(value) WITH (product_id uniqueidentifier ...)`. A malformed GUID would raise a conversion error inside the procedure (the service validates UUIDs before calling). `unit_price` is read as `decimal(14,2)`, so more than 2 decimals are rounded by the service (`round(price, 2)`) before sending.
45. **`CONVERT(decimal(16,2), quantity) * unit_price` as persisted computed column** - deterministic, so PERSISTED is allowed; unrun.
46. **All items invalid with `skip_invalid_items=1`** rolls back the whole sale and answers with the FIRST skipped item's error (409 / 404 / 422), not a 201 with an empty sale. Assumed that is what a client wants.
47. **Duplicate lines of the same product** are processed as separate lines (two `sale_items` rows). Not merged.
48. **`EXEC` with `?` placeholders and a trailing `SELECT` of the OUTPUT variables** in one pyodbc batch (`SET NOCOUNT ON; DECLARE ...; EXEC dbo.usp_RecordSale @org_id = ?, ...; SELECT ...`). Standard pattern but unrun; `SET NOCOUNT ON` is what makes the SELECT the first result set. `None` for uniqueidentifier/decimal parameters relies on pyodbc sending an untyped NULL.
49. **Cash KPI refresh**: the dashboard refreshes the cash balance only after a quick-add sale there; sales made on the Sales page show on the next dashboard visit.
