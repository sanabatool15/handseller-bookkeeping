# Backend (FastAPI + SQL Server)

The program that checks the rules and talks to the database. Python, FastAPI, and `pyodbc` for SQL Server. No Redis, no Docker.

## How to run
From the `api/` folder (Python 3.12, [uv](https://docs.astral.sh/uv/) installed):
```
cp .env.example .env        # then edit the MSSQL_* lines
uv sync
uv run uvicorn index:app --reload --port 8000
```
Use `index:app` (the website calls `/api/...` and this app removes the `/api` part). Open http://localhost:8000/api/health: `database` must say `ok`. Interactive API list: http://localhost:8000/api/docs

## Settings (`api/.env`)

| Name | Meaning |
|---|---|
| `MSSQL_SERVER` | `localhost`, or `.\SQLEXPRESS`, or `localhost,1433` |
| `MSSQL_DATABASE` | `HandsellerDB` |
| `MSSQL_USER` / `MSSQL_PASSWORD` | leave both empty for Windows login, fill for SQL login (`sa`) |
| `MSSQL_DRIVER` | `ODBC Driver 18 for SQL Server` (or `17`) |
| `MSSQL_TRUST_SERVER_CERTIFICATE` | `1` for a local server |
| `JWT_SECRET` | any long random text (signs the login token) |
| `IDEMPOTENCY_TTL_SECONDS` | how long a saved answer is remembered (default 86400 = 24 h) |
| `ENABLE_DB_LAB` | `true` only for the classroom demo buttons |

## Three layers (one direction only)

```
routers/       the web address: read the request, call a service, return the answer
services/      the rules: validate, decide, call repositories
repository/    the ONLY place with SQL
```
Other folders: `core/` (settings, database connection, login tokens, the FastAPI app), `middleware/` (login check, idempotency, request id), `index.py` (entry point that handles the `/api` prefix), `scripts/apply_sql.py` (optional: runs the SQL files from the command line instead of SSMS).

## Rules that must not be broken
1. **No SQL outside `repository/`.**
2. **Every query on one row filters by `id` AND `org_id`.** This is how one business is kept away from another's data. A record of another business answers **404**, never 403.
3. **Every save (POST/PUT/PATCH) needs an `Idempotency-Key` header.** The same key twice returns the saved answer and does nothing twice. Answers are kept in the `idempotency_keys` table (script `08`). Server errors (5xx) are not kept.
4. **Money changes go through the stored procedures** (`usp_RecordSale`, `usp_VoidSale`, `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount`). Nothing else changes sales, expenses, stock or cash. See [SQL_TRANSACTIONS.md](SQL_TRANSACTIONS.md).
5. **Routers get the database with `DB` from `routers/deps.py`** (it saves before the answer is sent).

## Endpoints (all under `/api` when run with `index:app`)

| Area | Endpoints |
|---|---|
| Login | `POST /auth/register`, `POST /auth/login` |
| Sales | `POST/GET /sales`, `GET/PUT/DELETE /sales/{id}` (delete = void) |
| Expenses | `POST/GET /expenses`, `GET/PUT/DELETE /expenses/{id}` |
| Products | `POST/GET /products`, `GET/PUT/DELETE /products/{id}`, `POST /products/{id}/adjust-stock` |
| Customers | `POST/GET /customers`, `GET/PUT/DELETE /customers/{id}`, `GET /customers/{id}/summary` |
| Cash | `GET /cash/balance`, `GET /cash/ledger`, `GET /cash/summary` |
| Activity | `GET /db-logs`, `GET /db-logs/requests` |
| DB Lab (demo, needs `ENABLE_DB_LAB=true`) | `GET /db-lab/status`, `POST /db-lab/race-sale`, `/db-lab/deadlock`, `/db-lab/deadlock-fixed` |
| Health | `GET /health` |

## Common errors

| Answer | Meaning |
|---|---|
| 400 | `Idempotency-Key` missing |
| 401 | not logged in / bad token |
| 404 | not found (or belongs to another business) |
| 409 | duplicate (SKU, phone, email), not enough stock, customer/product still used, same key still running |
| 422 | invalid input |

## More
The database side is explained in [SQL_SERVER.md](SQL_SERVER.md) and [SQL_TRANSACTIONS.md](SQL_TRANSACTIONS.md). The website side is in [FRONTEND.md](FRONTEND.md).
