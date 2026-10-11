# 15. Transactions, races and deadlocks

## In one line
One sale changes four things: stock, sale lines, cash balance, ledger. Either **all four** are saved or **none**. This file also covers what happens when two people act at the same moment.

## ACID in simple words

| Letter | Meaning | Example here |
|---|---|---|
| Atomic | all or nothing | one item has not enough stock, the whole sale is undone |
| Consistent | the rules always hold | stock never below 0, balance matches the ledger |
| Isolated | people at the same time do not break each other | two buyers of the last item |
| Durable | saved data survives a crash | after COMMIT |

## Three words
* **COMMIT**: save the changes for good.
* **ROLLBACK**: undo everything since the transaction began.
* **Savepoint**: a bookmark inside a transaction. You can undo back to the bookmark and keep the earlier work. Used to skip one bad item and keep the others.

## The stored procedure
A **stored procedure** is a saved program inside the database. `usp_RecordSale` does the whole sale in one go:
1. Create the sale.
2. For each item, reduce stock (only if enough is left).
3. Save the sale lines.
4. Add the money to the cash balance.
5. Write a ledger row.
6. Save everything (COMMIT). If anything failed, undo everything (ROLLBACK).

Similar procedures: `usp_VoidSale` (cancel a sale), `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount` (change an amount).

When a normal business problem happens ("not enough stock"), the procedure does not crash. It returns a status and a message. The app turns that into a clear error for the user.

## Race condition
Two people do something at the same time and the result depends on timing.
Example: stock is 1. Two buyers both see "1" and both buy. One item is sold twice.
The fix: reduce stock with one command that checks and changes together. The database locks the row, so the second buyer waits, then sees 0 and is refused.

## Deadlock
User 1 holds product A and wants B. User 2 holds B and wants A. Both wait forever.
SQL Server notices, cancels one user (the **victim**, error **1205**), and the app **tries again**.
To avoid most deadlocks, the procedure always handles products in the same order.

## Activity page and DB Lab
* **Activity** shows each money request and what happened: committed, retried after a deadlock, rejected (a rule said no), or rolled back.
* **DB Lab** has buttons that create a race or a deadlock on purpose, so you can see it. It is a demo only.
* "Lock wait suspected" is a guess, based on how long the request took.

## Try it in SSMS (plain SQL, one window)

Commit and rollback:
```sql
USE HandsellerDB;
SELECT name, stock_qty FROM products;

BEGIN TRAN;
UPDATE products SET stock_qty = stock_qty - 1 WHERE sku = 'F3-MUG';
SELECT name, stock_qty FROM products WHERE sku = 'F3-MUG';   -- changed
ROLLBACK;
SELECT name, stock_qty FROM products WHERE sku = 'F3-MUG';   -- back to before
```
Change `ROLLBACK` to `COMMIT` and the change stays.

Savepoint:
```sql
BEGIN TRAN;
UPDATE products SET stock_qty = stock_qty - 1 WHERE sku = 'F3-MUG';
SAVE TRAN a;
UPDATE products SET stock_qty = stock_qty - 1 WHERE sku = 'F3-PEN';
ROLLBACK TRAN a;                 -- undoes only the Pen change
SELECT sku, stock_qty FROM products WHERE sku IN ('F3-MUG', 'F3-PEN');
ROLLBACK;                        -- undo the rest
```
(`F3-MUG` and `F3-PEN` are demo products. Create them in the Products page or use any two products.)

See a lock (two query windows):
1. Window A: `BEGIN TRAN; UPDATE products SET stock_qty = stock_qty + 1 WHERE sku = 'F3-MUG';` and do not commit.
2. Window B: run the same `UPDATE`. It hangs and waits.
3. Window A: `COMMIT;` Window B now finishes.
4. Put the stock back with `UPDATE products SET stock_qty = stock_qty - 2 WHERE sku = 'F3-MUG';`

Make a deadlock (two query windows, products `F3-MUG` and `F3-PEN`):
1. Window A: `BEGIN TRAN; UPDATE products SET stock_qty = stock_qty WHERE sku = 'F3-MUG';`
2. Window B: `BEGIN TRAN; UPDATE products SET stock_qty = stock_qty WHERE sku = 'F3-PEN';`
3. Window A: `UPDATE products SET stock_qty = stock_qty WHERE sku = 'F3-PEN';` (waits)
4. Window B: `UPDATE products SET stock_qty = stock_qty WHERE sku = 'F3-MUG';` After a few seconds one window gets error 1205.
5. In the other window run `COMMIT;`

The easiest way to show a race and a deadlock is the **DB Lab** page buttons.

## Questions a teacher may ask
* **Why a transaction?** So a sale is all or nothing.
* **COMMIT vs ROLLBACK?** Save vs undo.
* **Why a savepoint?** To undo one bad item and keep the rest of the sale.
* **How do you stop two buyers selling the last item twice?** One command checks and reduces stock together. The row lock makes the second buyer wait.
* **What is a deadlock and how do you handle it?** Two users waiting on each other. SQL Server cancels one, the app retries. Same order of work prevents most of them.
* **Why is the Activity log saved separately?** If it were part of the transaction, a rollback would erase it.
