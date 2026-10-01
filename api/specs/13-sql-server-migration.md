# SQL Server migration (Supabase/Postgres -> Microsoft SQL Server)

## What and why
The backend is moving from Supabase (Postgres via the `supabase` client) to Microsoft
SQL Server (T-SQL via `pyodbc`). The user runs everything manually (SSMS + `uvicorn`);
no Docker changes are part of the migration. DDL lives in `sql_server/NN_name.sql`
(numbered, re-runnable, each starts with `USE HandsellerDB`); manual verification
steps live in `sql_server/TEST_CASES.md`.

## It is sliced
Each slice ports one area end to end (SQL script + repository + service + router + tests).
**Status: F0a (foundation + auth) and F0b (everything else + Supabase removal) are done; there is
a single data path now** (`routers/deps.py::get_db`, SQL Server, per request, commit/rollback).

| Where | How it gets a connection |
|---|---|
| FastAPI routers | `routers/deps.py::get_db` (renamed from `get_sql_db`; the Supabase `get_db` is deleted) |
| Inngest job steps, MCP server, scripts | `core.clients.db_session()` (one connection + transaction, commit/rollback/close) or `run_in_db(fn)` (same, retried as a whole on deadlock 1205/1222) |
| Startup + `GET /health` | `services/health_service.py::check_database` -> `repository/health_repository.py::ping` (`SELECT 1`) |

`core/clients.py` keeps `get_db_connection/set_db_factory` (test seam) and Redis; `get_supabase/set_supabase`, the
`supabase` dependency and the `SUPABASE_*` settings are gone. Settings: `MSSQL_*` in `core/config.py`.

## How (conventions)
* `core/db.py`: `Db` (one pyodbc connection, autocommit off: `query`, `query_one`, `execute`,
  `commit`, `rollback`, `close`), `transaction(db)`, `run_with_deadlock_retry`, row
  normalisation (uniqueidentifier -> str, Decimal -> float, date/datetime -> ISO string),
  lazy `pyodbc` import. A UNIQUE violation (2627/2601) surfaces as
  `repository.base.DuplicateRecordError`.
* Only `repository/*.py` contains SQL; always `?`-parameterised; table/column names are literals.
  Every by-id statement on a tenant table also contains `org_id`
  (`tests/unit/test_repository_sql_rules.py` enforces this statically).
* Tests: in-memory fakes in `tests/fake_repos.py` installed by an autouse fixture in
  `tests/conftest.py`; real-DB tests under `tests/sqlserver/` gated by `RUN_MSSQL=1`.
* **OUTPUT and triggers:** SQL Server raises error 334 for `OUTPUT` without `INTO` on a table with an
  enabled trigger. Every table here has an `updated_at` AFTER UPDATE trigger, so repositories use
  `SET NOCOUNT ON; DECLARE @o TABLE (...); INSERT/UPDATE ... OUTPUT INSERTED.cols INTO @o ...; SELECT * FROM @o;`
  instead of the bare `OUTPUT INSERTED.*`. (Caveat: for UPDATE the returned `updated_at` is the pre-trigger
  value.) Later slices must follow the same pattern.

## Slice F0a: foundation + auth
* `sql_server/01_foundation.sql`: database, `orgs`, `users`, `idx_users_org_id`, triggers.
  `orgs.owner_id` and `users.org_id` are both NULLable because SQL Server has no deferrable FKs.
  `users.email` is UNIQUE. No RLS (app-layer `org_id` is the primary control, `10-known-limitations.md` #5).
* Registration runs in ONE transaction (user -> org -> `set_user_org`); a failure leaves no orphan rows;
  a duplicate email (pre-check or concurrent UNIQUE violation) is the existing 409 "Email already registered".

## Slice F0b: sales, expenses, agent jobs/logs, jobs, MCP, agent tools
* `sql_server/02_sales_expenses_agents.sql`: `sales`, `expenses`, `agent_jobs`, `agent_logs`, `idx_*_org_id`,
  `idx_agent_logs_job_id`, updated_at triggers, `ISJSON` checks on json columns, `agent_jobs.status` CHECK, no RLS.
  `agent_logs` now has `org_id` (every tenant statement must mention it; composite FK `(job_id, org_id)` ->
  `agent_jobs(id, org_id)` ties a log to its job's org). No `UNIQUE (job_id, step_name)` (see specs/17 #10).
* Repositories keep their function names/return shapes (`sales`/`expenses`/`agent_jobs`), with these deliberate
  changes: `agent_jobs_repository.add_log` and `get_completed_steps` take `org_id`; new `list_logs_for_job`,
  `list_sales_for_month`, `list_expenses_for_month`, `health_repository.ping`. `base.get_ownership` is now the SQL
  version over an allow-list (`get_ownership_sql` removed).
* Updates use one static statement with `COALESCE(?, column)` (the service strips `None`, so None never means
  "set NULL"); unknown update keys raise `ValueError` before any SQL. Deletes use `rowcount`.
* Month totals / category breakdowns are `SUM ... GROUP BY` over a half-open date range in SQL
  (`base.month_range`), `COALESCE(SUM(..),0)` so an empty month is 0.0; the ledger CSV also filters by month in SQL
  (it used to slice the newest 1000 rows in Python).
* JSON columns (`input_payload`, `result`, `error_details`, `insights_generated`) are `json.dumps` on write and
  `json.loads` on read in `agent_jobs_repository`, so the API still returns dicts.
* `sale_date`/`expense_date` are set explicitly to UTC "today" (`base.today_utc`), consistent with the UTC month used by jobs/MCP.
* `agent_job_service.trigger_financial_advice_job` commits the job row BEFORE sending the Inngest event.
* Job steps: gather/finalize run through `run_in_db` (deadlock retry); the agent step holds one `db_session()` for
  the run and rolls back before falling back to rule-based advice.
* Static guard now also sees SQL held in dicts / built by `+` inside functions (so `base._OWNERSHIP_SQL` is checked).

## Caveat: T-SQL has not been executed
No SQL Server was available while writing this. All T-SQL (DDL, triggers, repository statements,
the `datetimeoffset` output converter) is unrun. Verify with `sql_server/TEST_CASES.md` and
`RUN_MSSQL=1 pytest tests/sqlserver`, and expect to fix small syntax issues.

## Slice F5: transaction log + DB Lab
`sql_server/07_txn_log.sql` adds the append-only `txn_log` (deliberately no `updated_at`/trigger, no `created_by`; see its header and specs/17). `core/db.py` gains `Db.get_isolation_level/set_isolation_level`,
`error_number_of`, richer `run_with_deadlock_retry` hook events; `core/clients.py` gains `get_autocommit_connection()`/`set_autocommit_factory()` (a SEPARATE autocommit connection for the log). Design: specs/15 sections 8-9, UI: specs/16.
