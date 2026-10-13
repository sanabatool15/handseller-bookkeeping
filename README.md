# Handseller Bookkeeping (SQL Server edition)

A small bookkeeping app for a handseller: record **sales** and **expenses**, keep **products** with stock, keep **customers**, and watch the **cash balance**. It also has an **Activity** page and a **DB Lab** that show database transactions, races and deadlocks live.

This branch (`ssms-extended`) is built around **Microsoft SQL Server and SSMS**. All data is in SQL Server and you can look at every table in SSMS. You do **not** need Docker, Redis or any cloud service.

## What you need
* SQL Server (Express is fine) running on your computer, and **SSMS** to open it
* [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) (17 also works)
* Python 3.12 and [uv](https://docs.astral.sh/uv/)
* Node.js 20 or newer

## Set it up (about 10 minutes)

**0. Get the code (this branch).**
```
git clone -b ssms-extended https://github.com/sanabatool15/handseller-bookkeeping.git
cd handseller-bookkeeping
```
Already cloned the repo? Run `git fetch origin` then `git checkout ssms-extended`.

**1. Create the database (in SSMS).** Connect to your server, open each file in `sql_server/` **in this order** and press Execute: `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`. Running a file twice is safe. Then check:
```sql
USE HandsellerDB;
SELECT name FROM sys.tables ORDER BY name;
```
You should see 11 tables (`users`, `orgs`, `sales`, `products`, `customers`, `cash_ledger`...).

**2. Start the backend.**
```
cd api
cp .env.example .env     # on Windows PowerShell: copy .env.example .env
```
Open `api/.env` and set the connection:

| Your SQL Server | Settings |
|---|---|
| Express, Windows login | `MSSQL_SERVER=.\SQLEXPRESS`, leave `MSSQL_USER` and `MSSQL_PASSWORD` empty |
| Default instance, Windows login | `MSSQL_SERVER=localhost`, user and password empty |
| SQL login (`sa`) | `MSSQL_SERVER=localhost,1433`, `MSSQL_USER=sa`, `MSSQL_PASSWORD=your password` |

If you only have ODBC Driver 17, set `MSSQL_DRIVER=ODBC Driver 17 for SQL Server`. Then:
```
uv sync
uv run uvicorn index:app --reload --port 8000
```
Open http://localhost:8000/api/health. It should say `"database":"ok"`.

**3. Start the website** (new terminal, in the project root).
```
npm install
npm run dev
```
Open http://localhost:3000, click **Register**, and create your account.

## Use it
1. **Products:** add a product with a price and stock.
2. **Sales:** record a sale with products. Stock goes down, cash goes up.
3. **Expenses:** record an expense. Cash goes down.
4. **Cash:** see the balance and every money movement.
5. **Activity** and **DB Lab:** see transactions, races and deadlocks (for DB Lab set `ENABLE_DB_LAB=true` in `api/.env` and restart the backend).

## Look at it in SSMS
After doing something in the app, run in SSMS:
```sql
USE HandsellerDB;
SELECT name, stock_qty FROM products;
SELECT TOP 10 entry_type, amount, balance_after FROM cash_ledger ORDER BY created_at DESC;
SELECT * FROM cash_accounts;
```
Everything you did in the app is there. The manual tests with copy-paste queries are in [sql_server/TEST_CASES.md](sql_server/TEST_CASES.md).

## If something goes wrong

| Problem | Fix |
|---|---|
| `database` says `error` in `/api/health` | Wrong `MSSQL_SERVER` or login. Check the `api/.env` table above |
| `Cannot open database "HandsellerDB" (4060)` | You have not run the SQL files yet (step 1) |
| `Data source name not found` / driver error | Install ODBC Driver 18, or set `MSSQL_DRIVER` to the driver you have. List them: `uv run python -c "import pyodbc; print(pyodbc.drivers())"` |
| `connection refused` / error 1225 | In *SQL Server Configuration Manager* enable **TCP/IP** and restart the SQL Server service. Or use `MSSQL_SERVER=.\SQLEXPRESS` |
| `Login failed for user 'sa'` | Enable SQL logins: in SSMS right-click server, Properties, Security, "SQL Server and Windows Authentication mode", restart, then set a password for `sa` |
| Website shows network errors | The backend is not running on port 8000 |
| An action says it needs `Idempotency-Key` | You called the API by hand. The website adds it for you |

## Read more
* [docs/SQL_SERVER.md](docs/SQL_SERVER.md): tables and design choices in plain words
* [docs/SQL_TRANSACTIONS.md](docs/SQL_TRANSACTIONS.md): commit, rollback, savepoint, races, deadlocks
* [docs/BACKEND.md](docs/BACKEND.md) and [docs/FRONTEND.md](docs/FRONTEND.md)
* [sql_server/TEST_CASES.md](sql_server/TEST_CASES.md): manual tests for SSMS
