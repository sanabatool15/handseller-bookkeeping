# 13. Moving the database to SQL Server

## In one line
The app used to keep its data in Supabase. Now it keeps everything in **Microsoft SQL Server**.

## What changed for the user?
Nothing. Same pages, same buttons. Only the database under the app changed.

## How one request reaches the database

```
Browser -> router -> service -> repository -> SQL Server
```

* **router**: receives the web request.
* **service**: checks the rules ("is the amount valid?").
* **repository**: the only place that talks to the database.
* One database connection is used per request. When the request ends fine, it is saved (**commit**). If something fails, everything is undone (**rollback**).

## The tables (made by the 7 files in `sql_server/`)

| File | Tables it creates |
|---|---|
| `01_foundation.sql` | orgs (businesses), users |
| `02_sales_expenses_agents.sql` | sales, expenses, agent jobs, agent logs |
| `03_products.sql` | products |
| `04_customers.sql` | customers |
| `05_sale_items_cash_recordsale.sql` | sale_items, cash_accounts, cash_ledger |
| `06_expenses_cash.sql` | (adds expense support to the cash ledger) |
| `07_txn_log.sql` | txn_log (the Activity page) |

Run them in order in SSMS. Running a file twice is safe.

## Four ideas to remember
1. **org_id**: every table has it. It says which business owns the row. A business never sees another business's rows.
2. **Trigger**: a small rule inside the database. After any change to a row, it sets `updated_at` to the current time by itself.
3. **Foreign key**: a link between tables. Example: a sale points to a customer. The database refuses a link to something that does not exist.
4. **Placeholders**: the app never glues user text into SQL. It sends the values separately. This stops SQL injection.

## Try it in SSMS (simple queries)

```sql
USE HandsellerDB;

SELECT name FROM sys.tables ORDER BY name;   -- list all tables
SELECT * FROM orgs;                          -- the businesses
SELECT * FROM users;                         -- the users
```

See a trigger work (the `updated_at` time changes):

```sql
SELECT TOP 1 name, updated_at FROM products;
UPDATE products SET name = name WHERE id = (SELECT TOP 1 id FROM products);
SELECT TOP 1 name, updated_at FROM products;
```

## Status
Register, products, customers and normal sales were run on a real SQL Server. Void, expenses, cash edits and the DB Lab buttons still need a person to try them.

## Questions a teacher may ask
* **Why a trigger for `updated_at`?** So the time is always correct and nobody has to remember it.
* **Why `org_id` everywhere?** So one business can never read or change another business's data.
* **Why a 404 and not 403 for another business's record?** 403 would tell the attacker that the record exists.
* **Why is SQL only in the repository?** One place to check, one place to fix.
* **What is SQL injection and how is it stopped?** Attacker text turns into a command. Placeholders send values separately, so text stays text.
