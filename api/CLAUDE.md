# CLAUDE.md (backend rules)

Guidance for an AI agent changing `api/`. Human-friendly docs: `../README.md`, `../docs/BACKEND.md`, `../docs/SQL_SERVER.md`, `../docs/SQL_TRANSACTIONS.md`.

## What this is
FastAPI backend for a handseller bookkeeping app on **Microsoft SQL Server** (pyodbc, T-SQL scripts in `../sql_server/`). Branch `ssms-extended`.
There is no Redis, Docker, AI agent, MCP server or background job runner. Do not add them back.
Idempotency keys are stored in the `idempotency_keys` table (`../sql_server/08_idempotency.sql`).

## Rules
1. **Layers, one direction:** `routers/` -> `services/` -> `repository/`. Only `repository/` contains SQL. Routers do HTTP only; services hold the rules.
   (`txn_log_service`, `db_lab_service`, `idempotency_service`, `health_service` may use `core.clients` to open their own connections; they still run no SQL.)
2. **Every statement on one row filters by `id` AND `org_id`.** Another business's record answers **404**, never 403. Use `repository/base.py::get_ownership`.
3. **Every POST/PUT/PATCH needs an `Idempotency-Key` header** (middleware does it; do not bypass it; never save 5xx answers).
4. **Money changes only through the stored procedures** (`usp_RecordSale`, `usp_VoidSale`, `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount`). Stock is changed by one guarded `UPDATE ... WHERE stock_qty >= @q`, never "read, check in Python, write".
5. **Routers get the database with `DB`** from `routers/deps.py` (`Depends(get_db, scope="function")`) so commit/rollback happen before the response is sent.
6. **SQL Server details:** tables with AFTER UPDATE triggers need `OUTPUT cols INTO @table; SELECT * FROM @table` (never bare `OUTPUT INSERTED.*`, error 334). Always `?` placeholders, never string-built SQL.
7. **Keep `api/index.py`** as the entry point (`uvicorn index:app`): it strips the `/api` prefix the website uses.
8. CORS is `allow_origins=["*"]` (local development). Lock it down before any real deployment.
9. Password hashing is hand-rolled PBKDF2 in `core/security.py`. Migrate deliberately if you change it.

## Run
```
cd api
uv sync
uv run uvicorn index:app --reload --port 8000
```
There is no automated test suite in this branch. Verify with `../sql_server/TEST_CASES.md` (manual, SSMS) and by using the app.
Never commit a filled-in `.env`.
