# SQL Server migration (Supabase/Postgres -> Microsoft SQL Server)

## What and why
The backend is moving from Supabase (Postgres via the `supabase` client) to Microsoft
SQL Server (T-SQL via `pyodbc`). The user runs everything manually (SSMS + `uvicorn`);
no Docker changes are part of the migration. DDL lives in `sql_server/NN_name.sql`
(numbered, re-runnable, each starts with `USE HandsellerDB`); manual verification
steps live in `sql_server/TEST_CASES.md`.

## It is sliced
Each slice ports one area end to end (SQL script + repository + service + router + tests).
Until the last slice lands, **two data paths coexist**:

| Dependency | Backend | Used by |
|---|---|---|
| `routers/deps.py::get_sql_db` | SQL Server (`core.db.Db`, per-request, commit/rollback) | auth (slice F0a) |
| `routers/deps.py::get_db` | Supabase client (legacy, untouched) | sales, expenses, agent jobs, MCP, jobs |

When all slices are migrated, `get_db` (Supabase) is deleted and `get_sql_db` is renamed to
`get_db`. `core/clients.py` likewise keeps `get_supabase/set_supabase` next to the new
`get_db_connection/set_db_factory` until then. Settings: `MSSQL_*` in `core/config.py`.

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

## Caveat: T-SQL has not been executed
No SQL Server was available while writing this. All T-SQL (DDL, triggers, repository statements,
the `datetimeoffset` output converter) is unrun. Verify with `sql_server/TEST_CASES.md` and
`RUN_MSSQL=1 pytest tests/sqlserver`, and expect to fix small syntax issues.
