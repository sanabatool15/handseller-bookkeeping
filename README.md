# Handseller Bookkeeping

Bookkeeping app for a handseller business: products and stock, customers, sales, expenses, a cash ledger, and an AI financial advisor.
This branch (`ssms-extended`) runs on **Microsoft SQL Server** (managed from SSMS) and adds a transaction/concurrency demo layer
(Activity log and DB Lab) for a database course.

```
frontend   Next.js (app/, components/, lib/)         http://localhost:3000
backend    FastAPI + pyodbc (api/)                    http://localhost:8000
database   SQL Server, database HandsellerDB (sql_server/*.sql, run in SSMS)
extras     Redis (idempotency), Inngest (background jobs), FastMCP, OpenAI Agents SDK
```

## Where things are documented

| Document | What is in it |
|---|---|
| [`api/README.md`](api/README.md) | Backend reference: layering, endpoints, jobs, MCP, env variables, tests |
| [`api/specs/`](api/specs/) | Numbered design specs (see index below) |
| [`api/CLAUDE.md`](api/CLAUDE.md) | Rules and traps for AI agents changing the backend (read before editing) |
| [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) | Next.js frontend warning for AI agents; `CLAUDE.md` also pulls in `api/CLAUDE.md` |
| [`sql_server/`](sql_server/) | The T-SQL scripts `01`..`07` and [`TEST_CASES.md`](sql_server/TEST_CASES.md) (manual checks to run in SSMS) |

### Spec index (`api/specs/`)
- `01` architecture layering, `02` schema (legacy Postgres), `03` multi-tenancy, `04` idempotency, `05` Inngest jobs, `06` agents, `07` MCP, `08` Docker, `09` testing, `10` known limitations, `11` package-name collisions, `12` Vercel
- **SQL Server work:** `13` migration, `14` products/customers/sales/cash domain, `15` transactions and concurrency (ACID, deadlocks), `16` UI pages, `17` open questions and assumptions

## What is on this branch

1. **SQL Server migration** (F0a/F0b): Supabase/Postgres replaced by T-SQL via `pyodbc`; no Supabase code remains.
2. **F1 Products & stock**, **F2 Customers**, **F3 Sales with line items + cash ledger** (`usp_RecordSale`, `usp_VoidSale`),
   **F4 Expenses on the cash ledger** (`usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount`).
3. **F5 Activity page and DB Lab**: a live per-request transaction log, plus demos of a race (overselling), a forced deadlock and the fix.

> The T-SQL has **not been executed against a real SQL Server yet** (the authoring sandbox had none), so expect to find and fix some
> errors on first run. Follow `sql_server/TEST_CASES.md` and note failures.

## Run everything with one command (Docker Compose)

```bash
docker compose up --build
```
Needs only Docker Desktop. `compose.yaml` starts SQL Server, creates `HandsellerDB` by running `sql_server/01..07` (the one-shot `db-init`
service), Redis, the FastAPI backend (live reload), the Inngest dev server and the Next.js frontend.

| What | Where |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Inngest UI | http://localhost:8288 |
| SSMS | Server name `localhost,1433`, SQL Server Authentication, login `sa`, password `Handseller_Dev1!` (override with `MSSQL_SA_PASSWORD`), tick "Trust server certificate" |

- Data lives in the `mssql-data` volume and survives restarts. Reset everything with `docker compose down -v`.
- Re-apply the scripts after editing them: `docker compose run --rm db-init`.
- Optional `api/.env` (for `OPENAI_API_KEY`, `JWT_SECRET`, ...) is picked up automatically; the `MSSQL_*` and Redis values are set by compose.
- `ENABLE_DB_LAB` defaults to `true` in compose (local demo). The first start takes a few minutes (image pulls, `npm install`).
- Changing the SA password after the volume exists does not change it inside SQL Server: run `docker compose down -v` first.
- Windows login (Trusted_Connection) cannot work from a Linux container, which is why compose uses the `sa` login and its own SQL Server.
  To use the SQL Server already installed on your machine instead, follow the manual steps below.
- `compose.yaml` was written without being able to start Docker in the authoring sandbox, so it is unverified: send the error output if something fails.

## Run it locally without Docker (separate terminals)

### 0. Prerequisites
- Git, Node.js 20+, Python 3.11+
- SQL Server (Developer or Express) and SSMS
- **Microsoft ODBC Driver 18 for SQL Server** (needed by `pyodbc`)
- Redis on `localhost:6379` (required for the `Idempotency-Key` middleware). On Windows use WSL or Docker: `docker run -p 6379:6379 redis:7`

### 1. Get this branch
```bash
git fetch origin ssms-extended
git switch -c ssms-extended --track origin/ssms-extended   # or: git checkout -b ssms-extended origin/ssms-extended
```
Your local `main` and `aws` branches are untouched.

### 2. Create the database (SSMS)
1. Connect to your instance (for example `localhost` or `localhost\SQLEXPRESS`).
2. File > Open > File, then open each script from `sql_server/` and press **Execute** (F5), **in this order**:
   `01_foundation.sql`, `02_sales_expenses_agents.sql`, `03_products.sql`, `04_customers.sql`,
   `05_sale_items_cash_recordsale.sql`, `06_expenses_cash.sql`, `07_txn_log.sql`.
   `01` creates `HandsellerDB`; every script starts with `USE HandsellerDB`. They are re-runnable.
3. Check: `USE HandsellerDB; SELECT name FROM sys.tables;`

### 3. Configure and start the backend
```bash
cd api
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env               # Windows: copy .env.example .env
```
Edit `api/.env` (see "Connecting to SQL Server" below), then:
```bash
uvicorn core.fastapi_app:app --reload --port 8000
```
Check `http://localhost:8000/health` (`checks.database` should be ok) and `http://localhost:8000/docs`.
To try the DB Lab set `ENABLE_DB_LAB=true` in `api/.env` and restart. Leave it `false` otherwise.

### 4. Start the frontend
```bash
# from the repo root
cp .env.example .env.local
npm install
npm run dev
```
Open `http://localhost:3000`. `next.config.ts` proxies `/api/*` to `http://localhost:8000`, so `NEXT_PUBLIC_API_URL=/api` is correct.

## Connecting to SQL Server

Set one of these in `api/.env`:

**Windows login (SSMS "Windows Authentication"):**
```
MSSQL_SERVER=localhost            # or localhost\SQLEXPRESS, or the name shown in SSMS "Server name"
MSSQL_DATABASE=HandsellerDB
MSSQL_USER=
MSSQL_PASSWORD=
MSSQL_DRIVER=ODBC Driver 18 for SQL Server
MSSQL_TRUST_SERVER_CERTIFICATE=1
```
**SQL login (for example `sa`):** same, with `MSSQL_USER` and `MSSQL_PASSWORD` filled in (enable Mixed Mode auth and TCP/IP in SQL Server Configuration Manager).

**Or a full ODBC string** (wins if set):
```
MSSQL_CONNECTION_STRING=DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=HandsellerDB;Trusted_Connection=yes;TrustServerCertificate=yes
```
Common problems: driver name mismatch (check the installed name in "ODBC Data Sources"), TCP/IP disabled, a named instance needing the SQL Browser service,
and running the API inside WSL/Docker while SQL Server is on Windows (use the Windows host IP, not `localhost`).

## Running queries in SSMS while the app runs
```sql
USE HandsellerDB;
SELECT * FROM orgs;          SELECT * FROM users;
SELECT * FROM products;      SELECT * FROM customers;
SELECT * FROM sales;         SELECT * FROM sale_items;
SELECT * FROM expenses;      SELECT * FROM cash_ledger;   -- table names: check with sys.tables
```
You can also call the procedures directly (for example `usp_RecordSale`) as described in `api/specs/15-transactions-and-concurrency.md`,
and open two query windows to reproduce blocking and deadlocks by hand.

## Tests (no SQL Server needed)
```bash
cd api && pytest tests/unit tests/integration -v
RUN_MSSQL=1 pytest tests/sqlserver -v      # real-DB tests, needs the setup above
npm run lint && npm run build              # frontend
```

## Not changed by this branch
Docker Compose files and the Vercel deployment still describe the old setup; the supported path here is local `uvicorn` + SSMS
(`api/specs/12-vercel-deployment.md`, `13-sql-server-migration.md`).
