# Test cases (easy version, SSMS)

Every test has three parts: **Do** (copy, paste, run), **You should see**, **Pass if**.
Run the tests in order. They take about 30 minutes in total.

## Before you start

1. Run the 7 scripts in `sql_server/` in SSMS, in order (`01` to `07`). Running a script twice is safe.
2. Start the app (backend and frontend), register, and make at least one account.
3. If you have more than one business (org), the blocks below use the first one. To see them: `SELECT id, name FROM orgs;`

### Make the demo products (run once)

```sql
USE HandsellerDB;
DECLARE @org uniqueidentifier = (SELECT TOP 1 id FROM orgs);
IF NOT EXISTS (SELECT 1 FROM products WHERE org_id = @org AND sku = N'F3-MUG')
  INSERT products (org_id, name, sku, price, stock_qty) VALUES (@org, N'Mug', N'F3-MUG', 10.00, 5);
IF NOT EXISTS (SELECT 1 FROM products WHERE org_id = @org AND sku = N'F3-PEN')
  INSERT products (org_id, name, sku, price, stock_qty) VALUES (@org, N'Pen', N'F3-PEN', 2.50, 1);
UPDATE products SET stock_qty = 5 WHERE org_id = @org AND sku = N'F3-MUG';
UPDATE products SET stock_qty = 1 WHERE org_id = @org AND sku = N'F3-PEN';
SELECT name, sku, price, stock_qty FROM products WHERE sku LIKE N'F3-%';
```
You should see: Mug (price 10, stock 5) and Pen (price 2.50, stock 1). Run this block again any time to reset the stock.

---

# Part A. Is the database built?

## A1. Tables, procedures and triggers exist
```sql
USE HandsellerDB;
SELECT name FROM sys.tables ORDER BY name;
SELECT name FROM sys.procedures ORDER BY name;
SELECT name FROM sys.triggers ORDER BY name;
```
You should see:
* tables: `agent_jobs, agent_logs, cash_accounts, cash_ledger, customers, expenses, orgs, products, sale_items, sales, txn_log, users`
* procedures: `usp_AdjustEntryAmount, usp_RecordExpense, usp_RecordSale, usp_VoidExpense, usp_VoidSale`
* triggers: one `trg_..._updated_at` per table (not `txn_log`)

Pass if: all of them are listed.

---

# Part B. The database refuses bad data (constraints)

A **constraint** is a rule inside the table. The database says no, even if the app has a bug.

## B1. Negative stock is refused (CHECK)
```sql
USE HandsellerDB;
INSERT products (org_id, name, sku, price, stock_qty)
SELECT TOP 1 id, N'Bad', N'BAD-1', 1, -1 FROM orgs;
```
You should see: error 547 (CHECK constraint). Nothing is inserted.
Also try `price = -1` instead of `stock_qty = -1`: same error.

## B2. Same SKU twice is refused (UNIQUE)
```sql
USE HandsellerDB;
INSERT products (org_id, name, sku, price, stock_qty) SELECT TOP 1 id, N'A', N'DUP-1', 1, 1 FROM orgs;
INSERT products (org_id, name, sku, price, stock_qty) SELECT TOP 1 id, N'B', N'DUP-1', 1, 1 FROM orgs;   -- fails
INSERT products (org_id, name, sku, price, stock_qty) SELECT TOP 1 id, N'C', N'dup-1', 1, 1 FROM orgs;   -- fails too (case ignored)
SELECT name, sku FROM products WHERE sku LIKE N'DUP%';
DELETE FROM products WHERE sku LIKE N'DUP%';
```
You should see: error 2627 twice. Only product A is in the table.
Pass if: you see exactly one row (A) before the delete.

## B3. Same email twice is refused
```sql
USE HandsellerDB;
INSERT users (email, hashed_password) VALUES (N'demo@x.com', N'h');
INSERT users (email, hashed_password) VALUES (N'DEMO@X.COM', N'h');   -- fails
DELETE FROM users WHERE email = N'demo@x.com';
```
You should see: error 2627 on the second insert.

## B4. Same phone twice is refused, but empty phones are fine
```sql
USE HandsellerDB;
INSERT customers (org_id, name, phone) SELECT TOP 1 id, N'DEMO A', N'555' FROM orgs;
INSERT customers (org_id, name, phone) SELECT TOP 1 id, N'DEMO B', N'555' FROM orgs;       -- fails
INSERT customers (org_id, name, phone) SELECT TOP 1 id, N'DEMO C', NULL FROM orgs;
INSERT customers (org_id, name, phone) SELECT TOP 1 id, N'DEMO D', NULL FROM orgs;         -- works
SELECT name, phone FROM customers WHERE name LIKE N'DEMO%';
DELETE FROM customers WHERE name LIKE N'DEMO%';
```
You should see: error 2601 on `DEMO B`. Three rows: A, C, D.
Pass if: the second `555` fails but both NULL phones work.

---

# Part C. Triggers

## C1. `updated_at` changes by itself
```sql
USE HandsellerDB;
SELECT name, created_at, updated_at FROM products WHERE sku = N'F3-MUG';
WAITFOR DELAY '00:00:02';
UPDATE products SET name = N'Mug' WHERE sku = N'F3-MUG';
SELECT name, created_at, updated_at FROM products WHERE sku = N'F3-MUG';
```
You should see: `updated_at` is later in the second result. You never set it yourself: the trigger did.

---

# Part D. Sales: commit, rollback, savepoint

Paste this **header** at the top of every block in Part D and E. It only finds the ids.

```sql
USE HandsellerDB;
DECLARE @org uniqueidentifier = (SELECT TOP 1 id FROM orgs);
DECLARE @user uniqueidentifier = (SELECT TOP 1 id FROM users WHERE org_id = @org);
DECLARE @mug uniqueidentifier = (SELECT id FROM products WHERE org_id = @org AND sku = N'F3-MUG');
DECLARE @pen uniqueidentifier = (SELECT id FROM products WHERE org_id = @org AND sku = N'F3-PEN');
DECLARE @sale uniqueidentifier, @total decimal(14,2), @status nvarchar(20), @msg nvarchar(400), @err int, @skipped nvarchar(max);
```

First reset the demo products (see "Make the demo products"). Mug stock 5, Pen stock 1.

## D1. A good sale is saved (COMMIT)
```sql
-- header here
DECLARE @items nvarchar(max) = CONCAT(N'[{"product_id":"', @mug, N'","quantity":2},{"product_id":"', @pen, N'","quantity":1}]');
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @category=N'retail', @items=@items,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @status AS status, @total AS total, @err AS error, @@TRANCOUNT AS open_transactions;
SELECT name, stock_qty FROM products WHERE sku LIKE N'F3-%';
SELECT balance FROM cash_accounts WHERE org_id = @org;
SELECT TOP 2 entry_type, amount, balance_after FROM cash_ledger WHERE org_id = @org ORDER BY created_at DESC;
```
You should see:
* status `committed`, total `22.50` (2 x 10 + 1 x 2.50), `open_transactions` 0
* Mug stock 3, Pen stock 0
* the balance went up by 22.50
* a new ledger row: `sale`, amount 22.50

Pass if: all four numbers match. One command changed stock, sale lines, balance and ledger together.

## D2. A bad sale undoes everything (ROLLBACK)
Pen stock is now 0, so asking for 5 Pens must fail.
```sql
-- header here
DECLARE @items nvarchar(max) = CONCAT(N'[{"product_id":"', @mug, N'","quantity":1},{"product_id":"', @pen, N'","quantity":5}]');
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @items=@items,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @status AS status, @err AS error, @msg AS message;
SELECT name, stock_qty FROM products WHERE sku LIKE N'F3-%';
```
You should see: status `rolled_back`, error `50001`, message "Not enough stock for Pen". **Mug stock is still 3**, even though the Mug line was fine. No new ledger row.
Pass if: nothing changed. This is **atomicity**: all or nothing.

## D3. Skip the bad item, keep the good ones (SAVEPOINT)
```sql
-- header here
DECLARE @items nvarchar(max) = CONCAT(N'[{"product_id":"', @mug, N'","quantity":1},{"product_id":"', @pen, N'","quantity":5},{"product_id":"', NEWID(), N'","quantity":1}]');
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @items=@items, @skip_invalid_items=1,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @status AS status, @total AS total, @skipped AS skipped_items;
SELECT name, stock_qty FROM products WHERE sku LIKE N'F3-%';
```
You should see: status `partial`, total `10.00`, two skipped items in the JSON (Pen: 50001, unknown product: 50002). Mug stock goes from 3 to 2.
Pass if: only the Mug was sold.

## D4. A quick sale with no products
```sql
-- header here
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @amount=40, @category=N'retail',
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @status AS status, @total AS total, @err AS error;
```
You should see: `committed`, total 40. Cash balance +40.
Now run it again without `@amount=40` and without items: you get `rolled_back`, error `50003` (invalid input).

## D5. The caller decides (nested transaction)
Here **you** open a transaction before calling the procedure. The procedure must not commit.
```sql
-- header here
DECLARE @items nvarchar(max) = CONCAT(N'[{"product_id":"', @mug, N'","quantity":1}]');
BEGIN TRAN;
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @items=@items,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @status AS status, @@TRANCOUNT AS open_transactions;       -- 1
SELECT stock_qty FROM products WHERE id = @mug;                    -- reduced by 1
ROLLBACK;
SELECT stock_qty FROM products WHERE id = @mug;                    -- back to what it was
```
You should see: status `committed`, but `open_transactions` is **1**. After `ROLLBACK` the stock is back.
Pass if: the stock returns. The procedure did not commit, you decided. Change `ROLLBACK` to `COMMIT` and the sale stays.

## D6. Cancel a sale (VOID)
This block sells 1 Mug and cancels it in one go.
```sql
-- header here
DECLARE @items nvarchar(max) = CONCAT(N'[{"product_id":"', @mug, N'","quantity":1}]');
EXEC dbo.usp_RecordSale @org_id=@org, @created_by=@user, @items=@items,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT,
     @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT stock_qty AS stock_after_sale FROM products WHERE id = @mug;
EXEC dbo.usp_VoidSale @org_id=@org, @sale_id=@sale, @voided_by=@user,
     @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT;
SELECT @status AS void_status;
SELECT stock_qty AS stock_after_void FROM products WHERE id = @mug;
SELECT TOP 2 entry_type, amount FROM cash_ledger WHERE org_id = @org ORDER BY created_at DESC;
```
You should see: stock goes down by 1, then comes back. Status `voided`. The ledger has a `sale` row (+10) and a `sale_void` row (-10).
Pass if: stock is back and the ledger has both rows (the old row stays as history).

## D7. The golden rule
```sql
USE HandsellerDB;
SELECT balance FROM cash_accounts;
SELECT SUM(amount) FROM cash_ledger;
```
Pass if: both numbers are equal (if you have older sales from before the ledger existed, they may differ).

---

# Part E. Expenses and changing an amount

## E1. Add, change and cancel an expense
```sql
-- header here
DECLARE @exp uniqueidentifier;
SELECT balance AS balance_before FROM cash_accounts WHERE org_id = @org;
EXEC dbo.usp_RecordExpense @org_id=@org, @created_by=@user, @amount=30, @category=N'rent', @voucher_reference=N'V-1',
     @expense_id=@exp OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT;
SELECT @status AS status;
SELECT balance AS balance_after_expense FROM cash_accounts WHERE org_id = @org;      -- 30 less

EXEC dbo.usp_AdjustEntryAmount @org_id=@org, @ref_type=N'expense', @ref_id=@exp, @new_amount=45, @adjusted_by=@user,
     @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT;
SELECT @status AS status;
SELECT balance AS balance_after_edit FROM cash_accounts WHERE org_id = @org;         -- 45 less than at the start

EXEC dbo.usp_VoidExpense @org_id=@org, @expense_id=@exp, @voided_by=@user,
     @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT;
SELECT @status AS status;
SELECT balance AS balance_after_void FROM cash_accounts WHERE org_id = @org;         -- same as the start
SELECT TOP 3 entry_type, amount FROM cash_ledger WHERE org_id = @org ORDER BY created_at DESC;
```
You should see: statuses `committed`, `adjusted`, `voided`. The balance goes down 30, then 15 more, then returns to the start. The ledger shows `expense` -30, `adjustment` -15, `expense_void` +45.
Pass if: `balance_after_void` equals `balance_before`.

## E2. Bad input is refused
```sql
-- header here
DECLARE @exp uniqueidentifier;
EXEC dbo.usp_RecordExpense @org_id=@org, @created_by=@user, @amount=0, @category=N'rent',
     @expense_id=@exp OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT;
SELECT @status AS status, @err AS error;
```
You should see: `rolled_back`, error `50003`. Nothing changed.

---

# Part F. Two people at the same time (use two query windows)

## F1. Race: the last item
Reset the demo products first. Then set Mug stock to 1:
```sql
USE HandsellerDB;
UPDATE products SET stock_qty = 1 WHERE sku = N'F3-MUG';
```
Now:

1. **Window A:**
```sql
USE HandsellerDB;
BEGIN TRAN;
UPDATE products SET stock_qty = stock_qty - 1 WHERE sku = N'F3-MUG' AND stock_qty >= 1;   -- (1 row affected)
```
Do not commit.

2. **Window B:**
```sql
USE HandsellerDB;
UPDATE products SET stock_qty = stock_qty - 1 WHERE sku = N'F3-MUG' AND stock_qty >= 1;
```
It hangs and waits.

3. **Window A:** run `COMMIT;`

You should see: Window B finishes with **(0 rows affected)**. Only one person got the last item.
Pass if: the final stock is 0 (not -1) and window B updated 0 rows. Reset the stock afterwards.

## F2. See the lock
While Window B is waiting (step 2 above), in a third window run:
```sql
SELECT request_session_id, resource_type, request_mode, request_status FROM sys.dm_tran_locks WHERE request_status = 'WAIT';
```
You should see: one waiting row. That is the lock wait.

## F3. Deadlock
Two windows, two products (`F3-MUG` and `F3-PEN`).

1. **Window A:** `BEGIN TRAN; UPDATE products SET stock_qty = stock_qty WHERE sku = N'F3-MUG';`
2. **Window B:** `BEGIN TRAN; UPDATE products SET stock_qty = stock_qty WHERE sku = N'F3-PEN';`
3. **Window A:** `UPDATE products SET stock_qty = stock_qty WHERE sku = N'F3-PEN';` (waits)
4. **Window B:** `UPDATE products SET stock_qty = stock_qty WHERE sku = N'F3-MUG';`

You should see: after a few seconds one window says "Transaction was deadlocked ... chosen as the deadlock victim" (error **1205**). Run `COMMIT;` in the other window.
Pass if: exactly one window is the victim.

---

# Part G. In the app (no SQL needed)

## G1. Products
* Add a product twice with the same SKU: the second is refused with a clear message.
* Add stock using the "adjust" button. Try to remove more than you have: refused, stock unchanged.
* Try to delete a product that has sales: refused. Make it inactive instead.

## G2. Customers
* Add a customer with a phone. Add another with the same phone: refused.
* Make a sale for a customer. Try to delete that customer: refused. Remove the customer from the sale first, then delete works.
* Search by the first letters of a name.

## G3. Sales and Cash
* Make a sale with products. Check Products (stock down) and Cash (balance and ledger up).
* Try to sell more than the stock: refused and nothing changes.
* Delete the sale: stock and cash go back.

## G4. Activity page
* After a good sale: one row `committed`.
* After a refused sale (not enough stock): one row `rejected (business rule)`. That is not a rollback.
* Click a request id to see the step-by-step timeline.

## G5. DB Lab (needs `ENABLE_DB_LAB=true` in `api/.env`, restart the backend)
Make a product with stock 1 and use these buttons:
* **Race sale, mode `unsafe`, 3 clients:** several clients "sell" the single item. You should see "OVERSOLD". The stock is put back afterwards.
* **Race sale, mode `safe`:** exactly 1 committed, the rest rejected. No oversell.
* **Force deadlock** (needs two products): one client shows error 1205, retries, and still commits.
* **Deadlock fixed:** both commit, nobody is cancelled.
Pass if: the results match. Each client has a link to its timeline on the Activity page.

---

# Part H. Automatic tests (optional)

From the `api/` folder:
```
$env:RUN_MSSQL = "1"        # PowerShell
uv run pytest tests/sqlserver -v
```
These run the same checks by themselves. If every test shows "skipped", `RUN_MSSQL` was not set. They create and delete their own data. If one fails, copy the error text and ask for help.

---

# Clean up after the demo
Void the demo sales (the Sales page, or Part D6) before deleting the demo products, because a sold product cannot be deleted:
```sql
DELETE FROM products WHERE sku IN (N'F3-MUG', N'F3-PEN');
```
