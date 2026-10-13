# SQL Server: the database, tables and design choices

This file has three parts: (1) how the app talks to SQL Server, (2) the tables for products, customers, sales and cash, (3) choices that were made. Transactions, races and deadlocks are in [SQL_TRANSACTIONS.md](SQL_TRANSACTIONS.md). Manual tests are in [../sql_server/TEST_CASES.md](../sql_server/TEST_CASES.md).

# Part 1. How the app uses SQL Server

## In one line
All data lives in **Microsoft SQL Server**. The app talks to it with plain SQL through `pyodbc` (a Python library). No Redis, no Docker, no cloud service is needed.

## How one request reaches the database

```
Browser -> router -> service -> repository -> SQL Server
```

* **router**: receives the web request.
* **service**: checks the rules ("is the amount valid?").
* **repository**: the only place that talks to the database.
* One database connection is used per request. When the request ends fine, it is saved (**commit**). If something fails, everything is undone (**rollback**).

## The tables (made by the 8 files in `sql_server/`)

| File | Tables it creates |
|---|---|
| `01_foundation.sql` | orgs (businesses), users |
| `02_sales_expenses.sql` | sales, expenses |
| `03_products.sql` | products |
| `04_customers.sql` | customers |
| `05_sale_items_cash_recordsale.sql` | sale_items, cash_accounts, cash_ledger, and the procedures `usp_RecordSale`, `usp_VoidSale` |
| `06_expenses_cash.sql` | the procedures `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount` |
| `07_txn_log.sql` | txn_log (the Activity page) |
| `08_idempotency.sql` | idempotency_keys (remembers answers so a double click does not do things twice) |

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
Register, products, customers and normal sales were run on a real SQL Server. Void, expenses, cash edits, idempotency keys and the DB Lab buttons still need a person to try them (see the manual tests).

## Questions a teacher may ask
* **Why a trigger for `updated_at`?** So the time is always correct and nobody has to remember it.
* **Why `org_id` everywhere?** So one business can never read or change another business's data.
* **Why a 404 and not 403 for another business's record?** 403 would tell the attacker that the record exists.
* **Why is SQL only in the repository?** One place to check, one place to fix.
* **What is SQL injection and how is it stopped?** Attacker text turns into a command. Placeholders send values separately, so text stays text.

---

# Part 2. Products, customers, sale items and cash

## In one line
Before, the app only noted "I sold something for X". Now it also knows **what** was sold, **to whom**, and **where the money went**.

## Who uses it and how?
A small seller (one business).
1. Adds products with a price and a stock count.
2. Optionally adds customers.
3. Records a sale: picks products and quantities. Stock goes down, cash goes up.
4. Records expenses. Cash goes down.
5. If a sale or expense was a mistake, **voids** it. Stock and cash go back.

## The tables

| Table | Simple meaning |
|---|---|
| `products` | the shelf: name, SKU (a code), price, stock |
| `customers` | the address book |
| `sale_items` | the lines on a receipt (product, quantity, price) |
| `cash_accounts` | the cash box: one row per business, with the current balance |
| `cash_ledger` | the notebook: one row for every money in or out. Never edited |

Each ledger row also stores the balance after it.

## The golden rule
**The balance in `cash_accounts` must always equal the sum of all amounts in `cash_ledger`.**

## Why is `customers` a separate table?
If a sale only had a typed name, you could not tell two "Ali"s apart, store a phone number, or see "how much did this customer buy". A customer table stores the person once. Each sale points to them. (The old typed name still works.)

## Rules the database enforces by itself

| Rule | Meaning |
|---|---|
| `CHECK` | stock can never go below 0, price can never be negative |
| `UNIQUE` | the same SKU cannot exist twice in one business |
| Unique phone | two customers in one business cannot share a phone. Customers with no phone are fine |
| Foreign key | a sale cannot point to another business's customer |
| Computed column | `line_total` = quantity x price, calculated by the database |

## Important decisions
* **Check and change stock in one step.** The app does not "read the stock, then write". It does one command: reduce stock only if enough is left. Why: two buyers could both read "1 left" and both buy it.
* **A customer with sales cannot be deleted.** Deleting would damage the sales history.
* **A product that was sold cannot be deleted.** Mark it inactive instead.
* **Cash may go below zero.** A seller can spend before cashing up. This is on purpose.

## Try it in SSMS (simple queries)

Look at the data:
```sql
USE HandsellerDB;
SELECT name, sku, price, stock_qty FROM products;
SELECT name, phone FROM customers;
SELECT * FROM cash_accounts;
SELECT TOP 10 entry_type, amount, balance_after FROM cash_ledger ORDER BY created_at DESC;
```

Check the golden rule (the two numbers must match):
```sql
SELECT balance FROM cash_accounts;
SELECT SUM(amount) FROM cash_ledger;
```

Watch the database say no (negative stock):
```sql
INSERT INTO products (org_id, name, sku, price, stock_qty)
SELECT TOP 1 id, 'Bad', 'BAD-1', 1, -1 FROM orgs;
```
You get error 547: the CHECK rule refused it.

Watch the database say no (same SKU twice):
```sql
INSERT INTO products (org_id, name, sku, price, stock_qty) SELECT TOP 1 id, 'A', 'DUP-1', 1, 1 FROM orgs;
INSERT INTO products (org_id, name, sku, price, stock_qty) SELECT TOP 1 id, 'B', 'DUP-1', 1, 1 FROM orgs;
DELETE FROM products WHERE sku = 'DUP-1';
```
The second insert fails with error 2627 (UNIQUE).

Best demo: make a sale in the app, then run the SELECT queries above and see stock, ledger and balance all change together.

## Questions a teacher may ask
* **Why a ledger and not just a balance?** A balance cannot explain itself. The ledger is the history.
* **Why is `line_total` a computed column?** It can never disagree with quantity and price.
* **Why can't I delete a customer who has sales?** To protect the sales history.
* **What if two people buy the last item?** One succeeds. The other gets "not enough stock" and nothing changes.
* **What does void do?** Puts the stock back and adds a reverse entry in the ledger. The old entry stays as history.

---

# Part 3. Choices that were made (and could change)

## In one line
While building, the AI had to guess some things. The important guesses are listed here with the reason.

## The main choices

| Choice | Why |
|---|---|
| Emails and SKUs ignore upper/lower case | SQL Server does this by default |
| Deleting a customer who has sales is refused | deleting would damage the sales history. Remove the link from the sales first |
| A sale links to a customer through `customer_id` **and** `org_id` | the database itself stops links to another business's customer |
| Procedures return "not enough stock" as a message, not a crash | a crash would undo the caller's other work too |
| Called from SSMS, the procedure saves by itself. Called from the app, the app saves at the end | depends on whether a transaction is already open |
| Cash balance may go below zero | a seller can spend before cashing up |
| Old sales and expenses (from before the ledger) are not added to the ledger | there is no "opening balance" yet |
| Changing a sale amount adds an adjustment row to the ledger | so the balance stays correct |
| A product that was sold cannot be deleted | mark it inactive instead |
| Saving now happens before the answer is sent to the browser | so the browser never sees a result that is not saved yet |
| Idempotency keys are stored in a SQL Server table, not Redis | one less thing to install; works for anyone who has SQL Server |
| DB Lab "safe" race only changes stock | so the demo leaves no sales or ledger rows behind |

## Known limits
* The stock change has no history table. The "reason" typed on a stock change is not saved.
* Activity and Cash pages show only the newest rows (no page buttons).
* Deleting a sold product shows a clear message only on an English SQL Server.
* Some features (void, expenses, cash edits, DB Lab buttons) still need a person to try them on the real server.

## Questions a teacher may ask
* **Why can the cash balance be negative?** A business choice. A guard is easy to add.
* **Why not delete a customer with sales?** To protect history.
* **Why does the procedure behave differently in SSMS and in the app?** SSMS has no transaction open, so the procedure opens and saves its own. The app already has one open, so the app saves at the end.
