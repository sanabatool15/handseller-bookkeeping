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

## Run everything with one command (Docker Compose, using your own SQL Server)

`compose.yaml` runs Redis, the FastAPI backend (live reload), the Inngest dev server and the Next.js frontend in Docker, and connects the backend
to **the SQL Server already installed on your machine** (for example `.\SQLEXPRESS`). A one-shot `db-init` service creates `HandsellerDB` there by
running `sql_server/01..07`. Then you browse it in SSMS exactly as usual. Needs Docker Desktop only.

### One-time SQL Server setup (a Linux container cannot use Windows Authentication)
1. **Enable TCP/IP with a fixed port.** SQL Server Configuration Manager > SQL Server Network Configuration > Protocols for SQLEXPRESS > TCP/IP: Enabled.
   Properties > IP Addresses tab > scroll to **IPAll**: clear "TCP Dynamic Ports", set **TCP Port = 1433**. OK.
2. **Allow SQL logins.** In SSMS connect with Windows Authentication, right-click the server > Properties > Security > "SQL Server and Windows Authentication mode".
3. **Create or enable a login.** Security > Logins > `sa` > Properties: set a password and Status > Login: Enabled (or create a new login, server role `sysadmin`).
4. **Restart the service.** Configuration Manager > SQL Server Services > SQL Server (SQLEXPRESS) > Restart.
5. **Windows Firewall:** allow inbound TCP 1433 if the connection is blocked (Windows Defender Firewall > Advanced > Inbound Rules > New Rule > Port 1433).
6. Check from SSMS: Server name `localhost,1433`, SQL Server Authentication, your login. If that works, Docker can reach it too.

### Run
Create a file named `.env` next to `compose.yaml` (it is git-ignored):
```
MSSQL_PASSWORD=your-sql-login-password
MSSQL_USER=sa
MSSQL_PORT=1433
```
```bash
docker compose up --build
```
| What | Where |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Inngest UI | http://localhost:8288 |
| Database | SSMS, your usual connection (`.\SQLEXPRESS`), database `HandsellerDB` |

- Re-apply the scripts after editing them: `docker compose run --rm db-init`. Check what happened: `docker compose logs db-init`.
- Optional `api/.env` (for `OPENAI_API_KEY`, `JWT_SECRET`, ...) is picked up automatically; the `MSSQL_*` and Redis values are set by compose.
- `ENABLE_DB_LAB` defaults to `true` in compose (local demo); set it in `.env` to change.
- The first start takes a few minutes (image pulls, `npm install`). Stop with `docker compose down`; your data stays in SQL Server.
- `compose.yaml` has not been run by the author (no Docker in the authoring sandbox): send the error output if something fails.

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
With [uv](https://docs.astral.sh/uv/) (reads `api/pyproject.toml`; `api/.python-version` pins Python 3.12):
```powershell
cd api
uv sync --extra dev                # creates api\.venv and installs the dependencies from pyproject.toml
copy .env.example .env             # macOS/Linux: cp .env.example .env
```
Edit `api/.env` (see "Connecting to SQL Server" below), then run (no need to activate the venv):
```powershell
uv run uvicorn index:app --reload --port 8000
```
Use `index:app`, not `core.fastapi_app:app`: the frontend proxy sends requests under `/api`, which `index.py` strips.
Without uv: `python -m venv .venv`, activate it, `pip install -r requirements.txt -r requirements-dev.txt`, then the same `uvicorn index:app ...`.
Use Python 3.12 or newer; an old 3.11 patch release can crash while importing the OpenAI Agents SDK (`KeyError: ~TContext`).
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
