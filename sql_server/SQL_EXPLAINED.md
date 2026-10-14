# SQL Explained (simple, file by file)

This file explains every script in `sql_server/` in plain words, for the viva and the report.
It does not change any SQL. Easy files are short; 05, 06 and 07 are longer because they are long.
Viva questions and answers (Roman Urdu) are at the end.

> Nothing here was run by the author of this file; it was written by reading the scripts.
> Run the scripts in SSMS and compare with `TEST_CASES.md`.

---

## 0. Words you will see everywhere

| Word | Plain meaning |
|---|---|
| `@name` | A **variable** or **parameter**: a small box with a name. `@qty` is "the quantity box". |
| `DECLARE @x int = 5;` | Make a box called `@x` that holds a whole number and put 5 in it. |
| `OUTPUT` parameter | A box the procedure fills and gives back to the caller (like a return value). |
| `GO` | An SSMS word that means "send everything above to the server now". It is not SQL itself. |
| `dbo.` | The default schema (folder) name of a table: `dbo.products`. |
| `N'text'` | Text that can hold any language (Unicode). |
| `uniqueidentifier` | A long random id (GUID) such as `3F2504E0-...`. Used for every `id`. |
| `datetimeoffset` | A date and time with a time zone. |
| `CREATE OR ALTER` | Create it, or replace it if it already exists. This is why scripts can be re-run. |
| `IF OBJECT_ID(...) IS NULL` / `IF NOT EXISTS (...)` | "Only create it if it is not there yet." Another reason scripts are re-runnable. |
| `org_id` | The id of the seller (tenant). Nearly every table has it. |

### The `updated_at` trigger (the same in every table)

```sql
CREATE OR ALTER TRIGGER dbo.trg_products_updated_at ON dbo.products AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF TRIGGER_NESTLEVEL(OBJECT_ID(N'dbo.trg_products_updated_at')) > 1 RETURN;
    UPDATE t SET updated_at = SYSUTCDATETIME()
    FROM dbo.products AS t INNER JOIN inserted AS i ON i.id = t.id;
END
```

- A **trigger** is code SQL Server runs by itself after something happens. Here: after every `UPDATE` on the table.
- `inserted` is a special table holding the new version of the rows that were just updated.
- The trigger sets `updated_at` to "now" for exactly those rows (join on `id`).
- The trigger's own `UPDATE` would fire the trigger again, so `IF TRIGGER_NESTLEVEL ... > 1 RETURN` stops the loop.
- Side effect: because tables have this trigger, `OUTPUT INSERTED.*` alone gives error 334, so the code uses
  `OUTPUT ... INTO @table` and then reads the table.

---

## 1. The files at a glance

| File | What it creates |
|---|---|
| `01_foundation.sql` | Database `HandsellerDB`, tables `orgs` and `users` |
| `02_sales_expenses.sql` | Tables `sales` and `expenses` |
| `03_products.sql` | Table `products` (stock) |
| `04_customers.sql` | Table `customers` and the link `sales.customer_id` |
| `05_sale_items_cash_recordsale.sql` | `sale_items`, `cash_accounts`, `cash_ledger`, procedures `usp_RecordSale`, `usp_VoidSale` |
| `06_expenses_cash.sql` | Procedures `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount` |
| `07_txn_log.sql` | Table `txn_log` (events for the Activity page) |
| `08_idempotency.sql` | Table `idempotency_keys` (stops double saves) |

Run them in this order, 01 to 08. Every script can be run again safely.

---

## 2. `01_foundation.sql` (short)

- Creates the database `HandsellerDB` if it does not exist, then `USE HandsellerDB`.
- **`orgs`**: one row per seller. Columns: `id`, `name`, `owner_id`, `created_at`, `updated_at`.
- **`users`**: login accounts. `email` is `UNIQUE` (no two accounts with the same email). `org_id` says which seller the user belongs to. `role` defaults to `member`.
- **Circular link:** `orgs.owner_id` points to `users.id` and `users.org_id` points to `orgs.id`. SQL Server cannot make both required at once, so both columns allow NULL. The app registers in one transaction: add user, add org, then update the user's `org_id`.
- `idx_users_org_id`: an index to find a seller's users quickly.
- Two `updated_at` triggers (section 0).

## 3. `02_sales_expenses.sql` (short)

- **`sales`**: one row per sale: `amount`, `category`, `description`, `customer_name`, `sale_date`. `org_id` points to `orgs`.
- **`expenses`**: the same idea: `amount`, `category`, `voucher_reference`, `expense_date`.
- `sale_date` / `expense_date` are the business date; `created_at` is when the row was really saved.
- An index on `org_id` for both tables, and the `updated_at` triggers.

## 4. `03_products.sql` (short)

- **`products`**: `name`, `sku` (product code), `price`, `stock_qty`, `reorder_level`, `is_active`.
- `CHECK (stock_qty >= 0)` and `CHECK (price >= 0)`: the database itself refuses negative stock or price (error **547**).
- `UNIQUE (org_id, sku)`: a SKU is unique inside one seller, but another seller may use the same SKU (violation = error **2627**).
- Index on `org_id` and the trigger.

## 5. `04_customers.sql` (short)

- **`customers`**: `name`, `phone`, `email`, `address`, `notes`.
- **Filtered unique index** `UQ_customers_org_phone ... WHERE phone IS NOT NULL`: a phone number must be unique inside a seller, but any number of customers may have no phone. (A plain UNIQUE would allow only one customer without a phone.) A violation is error **2601**.
- `UNIQUE (id, org_id)` on customers exists only to be the target of the next point.
- Adds `sales.customer_id` (optional) and a **composite foreign key** `(customer_id, org_id) -> customers(id, org_id)`: a sale can never point to another seller's customer.

## 6. `08_idempotency.sql` (short)

- **`idempotency_keys`**: every save request from the app carries an `Idempotency-Key`. The first answer is stored here under that key.
- If the same request arrives twice (double click, retry), the second one gets the saved answer and nothing is saved twice.
- Columns: `org_scope`, `idem_key` (together the primary key), `state` (`processing` or `done`), `status_code`, `response_body`, `created_at`.

---

## 7. `05_sale_items_cash_recordsale.sql` (long)

### 7.1 What the script adds

1. `UNIQUE (id, org_id)` on `sales` and `products`: needed as targets of the composite foreign keys below.
2. **`sale_items`**: the product lines of a sale.
   - `quantity > 0`, `unit_price >= 0` (CHECK).
   - `line_total` is a **computed column**: `quantity x unit_price`, stored by SQL Server, always correct.
   - Composite FKs `(sale_id, org_id)` and `(product_id, org_id)`: a line can only point to a sale and a product of the **same** seller. Deleting a sale deletes its lines (`ON DELETE CASCADE`).
3. **`cash_accounts`**: one row per seller with the current `balance`.
4. **`cash_ledger`**: the journal of every money movement. `amount` is `+` money in and `-` money out. Also `balance_after`, `entry_type` and a link to the sale (`ref_type`, `ref_id`). Only added to, never edited.
   - Golden rule: `cash_accounts.balance` always equals the sum of `cash_ledger.amount`.
5. Indexes and `updated_at` triggers for these tables.

### 7.2 `usp_RecordSale` step by step

**What it does:** records one sale and changes four things together: sale (and lines), product stock, cash balance, cash ledger. All or nothing.

**Inputs:** `@org_id` (seller), `@created_by`, `@customer_id`, `@customer_name`, `@category`, `@description`, `@amount` (only for a quick sale without items), `@items` (a JSON list of products and quantities), `@skip_invalid_items` (0 = one bad item cancels everything, 1 = skip bad items and keep the good ones).

**Outputs:** `@sale_id`, `@total`, `@status` (`committed`, `partial` or `rolled_back`), `@message`, `@error_number`, `@skipped_items`.

**Before step 1: the variables.** Plain helpers:
- `@own_tran`: "did I start the transaction, or did my caller?" (see section 10.1).
- `@tran_started`: did I open one yet?
- `@fail_number`, `@fail_message`: empty means "all fine so far"; a number means "something failed".
- `@lines`: a small table holding the items from the JSON.
- `@skipped`: a small table of items that were skipped.
- `@bal`: a small table that catches the new balance (needed because of the trigger).
- `@i`, `@n`: loop counters.

**Step 1: check the input (no table touched yet).**
- If `@items` is not valid JSON: fail with 50003.
- Otherwise read the JSON into `@lines` (`OPENJSON`). Lines are sorted by `product_id` so that two sales always lock products in the same order (this prevents most deadlocks).
- If there are no items and `@amount` is missing or not positive: fail with 50003.

**Step 2: open the transaction.**
- If I own it: `BEGIN TRANSACTION`. If the caller already has one: `SAVE TRANSACTION sp_record_sale` (a bookmark).
- Check that the org exists (50005) and the customer belongs to the org (50004).

**Step 3: insert the sale header** into `sales` (amount 0 for item sales; the real total is set in step 5).

**Step 4: the loop over the items** (`WHILE @i <= @n`). For each line:
1. Read the product, quantity and price of line `@i`.
2. `SAVE TRANSACTION sp_item`: a bookmark for this one item.
3. Check: product and quantity valid (50003), price not negative (50003).
4. **The important statement:**
   ```sql
   UPDATE products SET stock_qty = stock_qty - @qty
   WHERE id = @pid AND org_id = @org_id AND stock_qty >= @qty;
   ```
   It locks the row, checks that enough stock is there, and subtracts, all in one step. `@@ROWCOUNT = 0` means no stock (50001) or no such product (50002). The code then reads the name only to write a nice message.
5. If it worked, insert the line into `sale_items` (price defaults to the product's price).
6. If an item failed:
   - `@skip_invalid_items = 1`: `ROLLBACK TRANSACTION sp_item` undoes only this item, remember it in `@skipped`, carry on.
   - `@skip_invalid_items = 0`: remember the failure; the loop ends.
7. After the loop: if no item succeeded, the whole sale fails with the first reason.

**Step 5: totals, balance, ledger** (only if nothing failed):
- Total = sum of `line_total`; write it into `sales.amount`.
- If the seller has no cash account yet, create it (`UPDLOCK, HOLDLOCK` stop two first sales from both creating it).
- `UPDATE cash_accounts SET balance = balance + @total OUTPUT INSERTED.balance INTO @bal`: change and read the balance in one statement.
- Insert a `cash_ledger` row with type `sale`, `+total` and `balance_after`.

**Step 6: decide.**
- No failure: `COMMIT` (only if I own the transaction). Status `committed`, or `partial` if some items were skipped (with the skipped items as JSON in `@skipped_items`).
- Failure: roll back everything this procedure did (`ROLLBACK`, or only to `sp_record_sale` if the caller owns the transaction). Status `rolled_back`, the error number and message are returned.

**`CATCH` block:** if SQL Server raises a real error (deadlock 1205, constraint 547, ...), `XACT_STATE()` says if the transaction can still be rolled back partly (1) or only fully (-1). The code rolls back accordingly and returns status `rolled_back` with the error number. The API retries on 1205.

### 7.3 `usp_VoidSale` step by step

Cancels a sale and undoes its money effect.
1. Open the transaction (or savepoint), same as above.
2. Lock the sale row (`UPDLOCK, HOLDLOCK`) so two cancellations of the same sale cannot overlap. Not found (or another seller's sale): roll back, status `not_found`, error 50006.
3. Give the stock back: one `UPDATE products ... stock_qty + qty` over the sale's lines.
4. Add up what the ledger recorded for this sale (`sale` and `adjustment` rows). If it is not zero: lower the balance by that amount and write a `sale_void` row with the opposite sign. The old row stays as history.
5. Delete the lines and the sale. `COMMIT` (if I own it). Status `voided`.
6. `CATCH` works like in `usp_RecordSale`.

---

## 8. `06_expenses_cash.sql` (long)

### 8.1 First part: widen a CHECK

`cash_ledger.entry_type` may only be one of a fixed list. 05 allows `sale`, `sale_void`, `adjustment`; 06 drops that rule and creates it again with `expense` and `expense_void` added. A CHECK cannot be edited, so it is dropped and re-created, and only if `expense_void` is missing.

### 8.2 `usp_RecordExpense`

Same structure as `usp_RecordSale`, but simpler (no items, no loop).
1. Check `@amount > 0` (else 50003).
2. Open transaction or savepoint. Check the org exists (50005).
3. Insert the `expenses` row (category defaults to `general`).
4. Create the cash account if missing. `UPDATE cash_accounts SET balance = balance - @amount ... OUTPUT ... INTO @bal`.
5. Insert a `cash_ledger` row: type `expense`, **negative** amount.
6. `COMMIT` or roll back and return `rolled_back` with the error number. `CATCH` as before.

Design decision: the balance **may go negative**. A seller often pays before cashing up, so there is no `balance >= 0` rule.

### 8.3 `usp_VoidExpense`

Same shape as `usp_VoidSale`: lock the expense row; not found = 50007. Add up what the ledger recorded for it (`expense` and `adjustment` rows, negative numbers); raise the balance by that amount; write an `expense_void` row (positive); delete the expense; `COMMIT`.

### 8.4 `usp_AdjustEntryAmount`

Changes the amount of a sale or expense and records **only the difference**.
1. Check `@ref_type` is `sale` or `expense`, and `@new_amount > 0` (50003).
2. Open transaction or savepoint. Read the current amount with a lock. Sale not found = 50006, expense not found = 50007. A sale **with line items** is refused (50008, status `not_allowed`) because its amount is the sum of its lines.
3. `delta = new - old`. If 0: status `unchanged`, nothing is posted.
4. Otherwise update the amount; for a sale the cash effect is `+delta`, for an expense `-delta`. Update the balance and write an `adjustment` ledger row.
5. `COMMIT` / roll back as before.

It is an extra feature (not in the proposal). The reason it exists: after editing an amount, balance still equals the ledger sum.

---

## 9. `07_txn_log.sql` (long)

**Purpose:** the Activity page shows what happened in each request. This table stores those events.

**`txn_log` columns:**
| Column | Meaning |
|---|---|
| `id` | Auto-increasing number (`IDENTITY`), a tiebreaker for events at the same time |
| `request_id` | Groups the events of one request |
| `org_id` | Which seller (a seller sees only its own events) |
| `operation` | e.g. `record_sale`, `void_sale`, `lab_deadlock` |
| `step` | What happened. Allowed values (CHECK): `txn_started`, `lock_wait_suspected`, `deadlock_1205_caught`, `lock_timeout_caught`, `retry_triggered`, `rolled_back`, `committed`, `business_rejected` |
| `isolation_level` | e.g. READ COMMITTED |
| `status`, `error_number`, `message` | Short result of the step |
| `duration_ms` | How long the attempt or request took |
| `retry_no` | 0 for the first try, 1 for the first retry, ... |
| `created_at` | When the event happened (set by the app) |

**Important design points:**
- **Append-only:** rows are only inserted, never updated, so there is no `updated_at` and no trigger.
- **Written on a separate connection after the business transaction ended.** If the log were written inside the transaction, a rollback would delete the log too, and a rolled-back request is exactly the one you want to see.
- `lock_wait_suspected` is a guess by the app from elapsed time. It is not read from SQL Server's lock manager.
- Two indexes: `(org_id, created_at DESC)` for the list, and `(org_id, request_id)` for one request's timeline.
- Optional (commented, not run): `ALTER DATABASE HandsellerDB SET ALLOW_SNAPSHOT_ISOLATION ON;` is needed only for the SNAPSHOT choice in DB Lab.

---

## 10. Ideas used in 05 and 06, explained once

### 10.1 `@own_tran`: who owns the transaction?
- From SSMS you call the procedure with no transaction open (`@@TRANCOUNT = 0`): the procedure does `BEGIN TRANSACTION ... COMMIT` itself.
- The Python API uses `autocommit OFF`, which means a transaction is already open when the procedure starts. The procedure must **not** commit then (the caller commits), so it sets a **savepoint** and on failure rolls back only to that savepoint.
- That is why the same `IF @own_tran = 1 ... ELSE SAVE TRANSACTION ...` appears many times. It is the main reason the code looks long.

### 10.2 Savepoint
`SAVE TRANSACTION name` is a bookmark inside a transaction. `ROLLBACK TRANSACTION name` undoes work back to that bookmark only. Used per item in `usp_RecordSale` (skip a bad item, keep the good ones) and per procedure when nested.

### 10.3 `SET XACT_ABORT ON`
If a run-time error happens, the whole transaction is cancelled instead of being left half done.

### 10.4 TRY...CATCH and `XACT_STATE()`
Code in `BEGIN TRY` runs; if an error happens, `BEGIN CATCH` runs. `XACT_STATE()`: `1` = the transaction is fine and can be rolled back partly, `-1` = it is broken and only a full `ROLLBACK` is allowed, `0` = no transaction.

### 10.5 Business errors are OUTPUT values, not raised errors
With `XACT_ABORT ON`, a raised error breaks the caller's transaction too. So things like "not enough stock" are returned in `@status`, `@error_number`, `@message`. Business numbers:
`50001` not enough stock, `50002` product not found, `50003` invalid input, `50004` customer not found, `50005` organisation not found, `50006` sale not found, `50007` expense not found, `50008` not allowed.
Any other number is a real SQL Server error (e.g. 1205 deadlock, 547 constraint).

### 10.6 The guarded `UPDATE` (stops overselling)
`UPDATE products SET stock_qty = stock_qty - @q WHERE ... AND stock_qty >= @q` is one statement. The wrong way is "read stock, check in the program, write back": two buyers could both read "1 left" and both buy.

### 10.7 `UPDLOCK, HOLDLOCK`
A hint that says "lock this row (or this empty spot) now and keep the lock until the transaction ends". Used so two requests cannot both create the cash account, or both cancel the same sale.

### 10.8 `OUTPUT ... INTO @bal`
Changes a row and catches its new value in a table variable in the same statement. Needed because of the `updated_at` trigger (otherwise error 334).

### 10.9 Table variables (`@lines`, `@skipped`, `@bal`)
Small temporary tables that live inside the procedure. A `ROLLBACK` does **not** undo them, which is exactly why `@skipped` still remembers an item after `ROLLBACK ... sp_item`.

### 10.10 Multi-tenancy
Every table has `org_id`. Every statement filters by `id AND org_id`. Foreign keys are composite `(x_id, org_id)`, so even a bug cannot link rows of two sellers. Another seller's record answers 404.

---

## 11. What the proposal promised and where it is

| Proposal | Where |
|---|---|
| Tenants | `orgs` |
| Customers, Products | `customers`, `products` |
| Sales_Ledger | `sales` + `sale_items` + `cash_ledger` |
| Expenses | `expenses` |
| COMMIT / ROLLBACK / SAVEPOINT | `usp_RecordSale` (05) and the other procedures |
| Concurrency, S/X locks, isolation levels | DB Lab and SSMS tests (`TEST_CASES.md`) |
| Deadlock and Wait-For Graph | DB Lab "Force deadlock"; graph in SSMS (Extended Events `system_health`) |
| TRY...CATCH recovery | `CATCH` blocks in every procedure |
| `sp_RecordSale(@TenantID, @ProductID, @Qty)` | `usp_RecordSale` (same idea; `@org_id`, many items) |
| `sp_LogExpense(@TenantID, @Amount, @Category)` | `usp_RecordExpense` (`@org_id`, `@amount`, `@category`) |
| `fn_CalculateRunningBalance`, `fn_GetMonthlyReport` | **Not implemented.** Balance = sum of `cash_ledger`; the monthly report is a plain query. |
| Precedence graph | Not a database object; drawn on paper in the report if needed |
| System and transaction logs | `txn_log` and the Activity page |

Name differences: Tenant = `org`, `Sales_Ledger` = `sales`, `sp_` = `usp_`.

---

## 12. Viva questions and answers (Roman Urdu)

**1. `@` kya hota hai?**
Variable ya parameter. Ek chhota dabba jis mein value rakhte hain, jaise `@qty` mein quantity. Procedure ko input `@` wale parameter se milta hai aur jawab `OUTPUT` wale parameter se wapas jata hai.

**2. Seedhi query ki jagah stored procedure kyun?**
Ek sale mein char cheezein badalti hain: sale, stock, cash balance aur ledger. Procedure mein yeh sab ek transaction mein hoti hain, to ya sab hoti hain ya kuch nahi. Logic ek hi jagah rehta hai aur Python sirf procedure bulata hai.

**3. Procedure ke andar loop kyun hai?**
Kyunke ek sale mein kai products ho sakte hain (cart). Loop har product ke liye stock kam karta hai aur line likhta hai. Ek product wali sale mein loop ki zaroorat nahi.

**4. Atomicity kahan dikhti hai?**
`usp_RecordSale` mein. Agar Pen ka stock kam ho to poori sale ROLLBACK ho jati hai, aur pehle wale Mug ka stock bhi wapas aa jata hai (error 50001).

**5. Savepoint kya hai aur kyun?**
Transaction ke andar bookmark. `@skip_invalid_items = 1` mein har item ka apna savepoint hai. Bura item sirf apne savepoint tak undo hota hai, achhe items rehte hain, status `partial` aata hai.

**6. Do log ek saath aakhri item khareedein to?**
Stock ka ek hi `UPDATE ... WHERE stock_qty >= @qty` hai. Pehla row lock karke stock kam karta hai. Doosra wait karta hai, phir stock 0 dekhta hai aur `ROWCOUNT = 0` aata hai, yani rejected. Stock kabhi -1 nahi hota.

**7. Dirty read kya hai?**
Kisi ki adhuri (uncommitted) change ko parh lena. `READ UNCOMMITTED` mein hota hai. Default `READ COMMITTED` mein parhne wala wait karta hai jab tak doosra commit ya rollback na kare.

**8. Deadlock kya hai aur kaise bachate hain?**
Do transactions ek doosre ka lock maangti hain aur dono atak jati hain. SQL Server ek ko victim bana kar error 1205 deta hai. Hum products ko `product_id` ke order mein lock karte hain, to dono ka order same hota hai aur deadlock kam hota hai. Phir bhi ho jaye to API 1205 pakad kar dobara try karti hai.

**9. TRY...CATCH aur `XACT_STATE()` kya hain?**
Error aaye to CATCH chalta hai. `XACT_STATE()` batata hai ke transaction abhi theek hai (1, partial rollback ho sakta hai), toot chuki hai (-1, sirf full rollback), ya hai hi nahi (0).

**10. `@own_tran` kya hai?**
SSMS se bulao to procedure khud transaction kholti aur commit karti hai. Python pehle se transaction khol deta hai, to procedure commit nahi karti, sirf savepoint lagati hai. `@own_tran` yeh yaad rakhta hai ke transaction kis ki thi.

**11. Business error `THROW` se kyun nahi, OUTPUT se kyun?**
`XACT_ABORT ON` ke saath error se caller ki poori transaction bhi toot jati hai. "Stock kam hai" koi technical error nahi, isliye usko `@status` aur `@error_number` mein wapas dete hain.

**12. Multi-tenant kaise?**
Har table mein `org_id`. Har query `id AND org_id` se filter hoti hai. Doosre seller ka record maange to 404 aata hai, 403 nahi, taake pata hi na chale ke woh record hai.

**13. Composite foreign key kyun?**
`(sale_id, org_id)` jaisi FK se line sirf usi seller ki sale ya product se judti hai. Code mein bug ho tab bhi database doosre seller ka link banane nahi deta.

**14. Trigger kya hai aur recursion kyun roka?**
Trigger woh code hai jo SQL Server khud chalata hai. Yahan `UPDATE` ke baad `updated_at` set karta hai. Us ka apna `UPDATE` trigger ko dobara chala deta, is liye `TRIGGER_NESTLEVEL > 1` par rok dete hain.

**15. Filtered unique index kya hai?**
Phone sirf tab unique jab phone maujood ho (`WHERE phone IS NOT NULL`). Is se phone ke bina kai customers ho sakte hain, aur ek seller ke do customers ka phone same nahi ho sakta.

**16. Sale void mein delete kyun, ledger mein kya hota hai?**
Sale delete hoti hai lekin ledger mein purani row rehti hai aur ek nayi `sale_void` row ulti sign ke saath aati hai. Ledger sirf badhta hai, is se hisab ki history bachti hai.

**17. Balance negative kyun ho sakta hai?**
Seller aksar cash milne se pehle kharcha kar deta hai (stall fee, packaging). Isliye expense par balance ki shart nahi rakhi. Balance hamesha ledger ke sum ke barabar rehta hai.

**18. Proposal ke naam (`Tenants`, `sp_RecordSale`) alag kyun?**
Naam badle hain, cheez wahi hai: Tenant = `org`, `sp_` = `usp_`, Sales_Ledger = `sales` + `sale_items` + `cash_ledger`. Mapping section 11 mein hai.

**19. Functions (`fn_...`) kyun nahi hain?**
Abhi nahi banaye. Balance `cash_ledger` ke sum se aur monthly report ek normal query se nikalti hai. Yeh Future Enhancements mein hain. (Faisla baaki: functions banane hain ya proposal se hatana hai.)

**20. `txn_log` alag connection par kyun likha jata hai?**
Agar log transaction ke andar likhte, to rollback ke saath log bhi mit jata. Hum chahte hain ke rolled-back request ka bhi record rahe.

**21. Idempotency key kya hai?**
Har save request ki ek unique key hoti hai. Dobara click ya retry ho to pehla jawab wapas milta hai aur sale dobara nahi banti.

**22. Two-Phase Locking (2PL) kahan hai?**
SQL Server update par exclusive lock lagata hai aur commit ya rollback tak rakhta hai. Lock lene ka phase transaction ke dauran, aur chhodne ka phase end par, yani strict 2PL jaisa. Hum alag se 2PL code nahi likhte, SQL Server khud karta hai. Dekhne ke liye `sys.dm_tran_locks` ya DB Lab.

**23. Precedence graph kahan hai?**
Yeh database object nahi, ek kaagzi analysis hai. Report mein T1 aur T2 ke read/write se banta hai. Cycle ho to schedule serializable nahi hota. (Report mein abhi shamil karna baaki hai.)
