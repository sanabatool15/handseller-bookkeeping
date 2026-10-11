# 14. Products, customers, sale items and cash

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
