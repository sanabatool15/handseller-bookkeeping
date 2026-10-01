# Inventory and cash domain (F1 onward)

This spec grows slice by slice. Each section says what was built, why, where it is tested, and what is NOT covered.

## F1: Products & stock

### What
* Table `products` (`sql_server/03_products.sql`): `id`, `org_id`, `created_by`, `name`, `sku`, `price decimal(14,2)`,
  `stock_qty int`, `reorder_level int`, `is_active bit`, `created_at`, `updated_at` (+ trigger). `UNIQUE (org_id, sku)`,
  `idx_products_org_id`, CHECKs for `price`, `stock_qty`, `reorder_level` all `>= 0`.
* `repository/products_repository.py` -> `services/products_service.py` -> `routers/products_router.py`
  (`/products`, see `api/README.md` for the endpoint table). UI: `app/(app)/products/page.tsx`, `components/product-form-modal.tsx`, `lib/use-products.ts`.
* `products` is in the `get_ownership` allow-list and in the static guard's tenant tables.

### Why (design decisions)
* **`CHECK (stock_qty >= 0)` is the DB-level consistency guard.** The later sale procedure will decrement stock inside a
  transaction; whatever the application does, SQL Server refuses negative stock (error 547) and the transaction rolls back.
* **Adjust-stock is one race-safe statement**: `UPDATE products SET stock_qty = stock_qty + ? ... WHERE id = ? AND org_id = ? AND stock_qty + ? >= 0`
  (`OUTPUT ... INTO @o`). The row lock serialises concurrent adjustments, so there is no read-modify-write window. Zero rows is
  ambiguous (unknown/other-org vs. would go negative); the service then runs a scoped `get_ownership` ONLY to choose between 404 and 409.
  The decision "may this adjustment happen" is never taken from a prior read. (If the product is deleted between the two statements the answer is 404, which is correct.)
* **Stock is changed only by adjust-stock** (PUT cannot set `stock_qty`); initial stock is accepted on create.
* **409 for duplicate SKU** (UNIQUE violation 2627/2601 -> `DuplicateRecordError` -> `DuplicateSkuError`) and for insufficient stock; 422 for validation; 404 cross-tenant.
* Quantities (stock, delta, reorder level) are capped at 1,000,000 so `stock_qty + delta` can never overflow `int`.
* `low_stock` means `stock_qty <= reorder_level` (so a product with reorder level 0 is "low" only when out of stock).

### Where tested
* Service unit tests `tests/unit/test_products_service.py`; integration `tests/integration/test_products_api.py`
  (CRUD, JSON shape, 422, 409 dup SKU, 409 insufficient, cross-tenant 404 on GET/PUT/DELETE/adjust, missing key 400, idempotent replay).
* Static SQL guard (`test_repository_sql_rules.py`, incl. the adjust statement shape) and recorded-statement shapes (`test_repository_sql_shapes.py`).
* Real DB (gated `RUN_MSSQL=1`): `tests/sqlserver/test_products_sqlserver.py` (CHECKs, unique per org, trigger, isolation, 12-thread race). Manual: `sql_server/TEST_CASES.md` F1-01..F1-12.

### Not covered / limitations
* T-SQL has not been executed (no SQL Server in the authoring sandbox); the in-memory fakes only model the semantics.
* No stock-movement history: `reason` on adjust-stock is validated but not stored. No link from sales to products yet (later slice). *(Annotation, F3: `sale_items` now links sales to products and `usp_RecordSale` decrements stock.)*
* Hard delete only; once sales reference products, deletion must become soft (`is_active = 0`) or be blocked by FK. *(Annotation, F3: the FK now blocks deleting a sold product, surfacing as HTTP 500; see specs/17 #41.)*
* No search/text filter on the API (the UI filters client-side over the first 200 rows).

## F2: Customers

### What
* Table `customers` (`sql_server/04_customers.sql`): `id`, `org_id`, `created_by`, `name` (200, required), `phone` (32), `email` (320),
  `address` (500), `notes` (1000), `created_at`, `updated_at` (+ trigger), `idx_customers_org_id`, `UQ_customers_id_org (id, org_id)`.
* **`UQ_customers_org_phone` is a FILTERED unique index** `(org_id, phone) WHERE phone IS NOT NULL`: phones are unique per org, any number
  of customers can have no phone (a plain UNIQUE would allow only one NULL per org), other orgs may reuse a phone. Blank phones are stored as NULL
  by the service. Violation = error 2601 => `DuplicateRecordError` => 409.
* `sales.customer_id uniqueidentifier NULL` (added by the same script, guarded by `IF COL_LENGTH(...) IS NULL`, so re-runnable) with the
  COMPOSITE FK `FK_sales_customer (customer_id, org_id) -> customers (id, org_id)` and `idx_sales_org_customer (org_id, customer_id)`.
  The composite FK makes the database itself refuse a sale that points at another org's customer (belt and braces next to the service check).
* `repository/customers_repository.py` -> `services/customers_service.py` -> `routers/customers_router.py` (`/customers`, see `api/README.md`).
  UI: `app/(app)/customers/page.tsx`, `components/customer-form-modal.tsx`, `lib/use-customers.ts`; optional customer dropdown in the sales form.
* `customers` is in the `get_ownership` allow-list and the static guard's tenant tables.

### Why (design decisions)
* **Search** `GET /customers?q=`: prefix match on name OR phone, `LIKE ? ESCAPE '\'` with a bound pattern; `\ % _ [` in the user text are
  escaped in the repository, so they are literals. Max 100 characters (422). Case-insensitive (default collation).
* **Summary** `GET /customers/{id}/summary` = `{customer, total_sales, sale_count, last_sale_date}` from ONE statement:
  `customers c LEFT JOIN sales s ON s.customer_id = c.id AND s.org_id = c.org_id AND s.org_id = ? WHERE c.id = ? AND c.org_id = ? GROUP BY ...`
  (org_id applied to both tables; a customer without sales gives 0 / 0 / null).
* **Sale link**: `SaleCreate`/`SaleUpdate` accept optional `customer_id`. The service checks it with `get_ownership(table="customers")`
  (id AND org_id); a foreign-org and an unknown id give the same 404 `"Customer not found"`. The free-text `customer_name` is untouched and independent.
  Sales responses now contain `customer_id` (null when none). On `PUT /sales/{id}`, an omitted `customer_id` leaves the link, an explicit
  `null` unlinks it (the router now uses `model_dump(exclude_unset=True)`; other fields behave as before, null is still ignored).
* **Delete customer: 409, not "set sales.customer_id NULL"** (the safer option). Detaching would silently rewrite financial history
  (and `customer_name` may be empty, so the customer would be lost from those sales), and needs a two-statement transaction with a race window.
  Instead the repository runs one `DELETE ... WHERE id = ? AND org_id = ? AND NOT EXISTS (SELECT 1 FROM sales WHERE customer_id = customers.id AND org_id = ?)`.
  Zero rows is ambiguous, so the service runs a scoped `get_ownership` ONLY to choose between 404 (unknown/other org) and 409 (customer has sales).
  To remove such a customer, unlink its sales first (`PUT /sales/{id}` with `customer_id: null`). A sale inserted concurrently is stopped by the FK (error 547).
* **PUT semantics**: `name` is never cleared; `phone/email/address/notes` can be cleared with an explicit `null` or blank (a (flag, value) pair per
  column keeps the SQL static); omitted fields are untouched.

### Where tested
* Unit `tests/unit/test_customers_service.py`; integration `tests/integration/test_customers_api.py` (CRUD, 422, 409 duplicate phone, search incl. wildcard
  characters, summary, delete 409 / unlink / delete, cross-tenant 404 on every verb incl. summary, foreign `customer_id` on a sale => 404, idempotency).
* Static guard + recorded-statement shapes (`test_repository_sql_rules.py`, `test_repository_sql_shapes.py`).
* Real DB (gated `RUN_MSSQL=1`): `tests/sqlserver/test_customers_sqlserver.py`. Manual: `sql_server/TEST_CASES.md` F2-01..F2-13.

### Not covered / limitations
* T-SQL not executed (see F1). The fakes model the semantics only (e.g. LIKE escaping is verified on the statement/params, executed only by the gated tests).
* No pagination metadata and no sorting options; no per-customer sales list endpoint (use `GET /sales` and filter client side). Customers are hard-deleted (when allowed).
* `PUT /sales` cannot yet change `sale_date`; the summary's `last_sale_date` is the business date, not `created_at`.

## F3: Sale line items, cash ledger and atomic `usp_RecordSale`

### What
* `sql_server/05_sale_items_cash_recordsale.sql` (re-runnable): `sale_items` (`quantity > 0`, `unit_price >= 0`, `line_total` = persisted computed column
  `quantity * unit_price`, composite FKs `(sale_id, org_id) -> sales(id, org_id)` with `ON DELETE CASCADE` and `(product_id, org_id) -> products(id, org_id)`),
  `cash_accounts` (one row per org, `balance`), `cash_ledger` (append-only journal: `entry_type` in `sale | sale_void | expense | adjustment`, signed `amount`,
  `ref_type/ref_id`, `balance_after`, `entry_date`, `created_by`), `UQ_sales_id_org` / `UQ_products_id_org` (targets of the composite FKs), `idx_*_org_id`, `updated_at` triggers.
* Procedures `dbo.usp_RecordSale` and `dbo.usp_VoidSale` (heavily commented, they are course material). `cash_accounts` is created lazily inside the procedure.
* `repository/sales_repository.py` (`record_sale`, `void_sale`, items read-back), new `repository/cash_repository.py` + `services/cash_service.py` + `routers/cash_router.py`
  (`GET /cash/balance`, `GET /cash/ledger`). UI: line-items editor in the sale form, item count + item list in the sales table, "Skip invalid items" checkbox, cash balance KPI on the dashboard.
* Endpoint contract: `api/README.md` (F3 table).

### Why (design decisions)
* **Why the stock decrement is ONE statement** `UPDATE products SET stock_qty = stock_qty - @q WHERE id = @p AND org_id = @o AND stock_qty >= @q` and `@@ROWCOUNT` is the verdict.
  The "read then write" alternative (`SELECT stock ...; if stock >= q: UPDATE ... SET stock_qty = <value computed in the app>`) has a gap between the read and the write:
  two buyers both read "1 left", both pass the check, both write; one unit is sold twice (lost update / oversell). With one statement the engine takes the row lock, evaluates
  the guard on the committed value and writes, with no gap. Concurrent buyers queue on the lock; the loser re-evaluates after the winner commits, sees `0`, and updates zero rows.
  `CHECK (stock_qty >= 0)` stays as the last line of defence. Zero rows is ambiguous (unknown product vs. not enough stock) - a follow-up `SELECT name` only picks the MESSAGE, the decision was already taken atomically.
* **All-or-nothing by default, savepoints for partial.** `skip_invalid_items = 0`: the first bad item rolls back the whole sale. `= 1`: each item runs after `SAVE TRANSACTION sp_item`; a bad item is undone with
  `ROLLBACK TRANSACTION sp_item` and recorded in the `@skipped` table variable (table variables are not rolled back); valid items are kept (`partial`). If NO item is usable the whole sale is rolled back with the first reason.
* **Business errors are OUTPUT values, not raised errors.** With `XACT_ABORT ON` any raised error dooms the transaction (`XACT_STATE() = -1`), and then only a FULL rollback is possible, which would also destroy a caller's transaction.
  Numbers: 50001 insufficient stock (409), 50002 unknown/foreign product (404), 50003 validation (422), 50004 customer not found (404), 50005 org not found, 50006 sale not found. Engine errors (1205 deadlock, 547, ...) are caught by `CATCH`,
  reported as `rolled_back` and re-raised by the repository as `ProcedureError` (the deadlock retry in the service recognises 1205).
* **Cash**: `cash_accounts.balance` is updated in the same transaction by an atomic `balance = balance + @total` (`OUTPUT ... INTO` because of the trigger); the ledger row stores `balance_after`. Invariant (tested): balance == SUM(ledger.amount) per org.
  The hot-row update is the LAST statement of the transaction, so the lock is held briefly. First-sale creation of the account uses `UPDLOCK, HOLDLOCK` on the key range so two concurrent first sales cannot both insert.
* **Lock order**: items are processed sorted by `product_id`, so two sales with the same products lock them in the same order (fewer deadlocks). Remaining deadlocks are retried (`run_with_deadlock_retry`, up to 3 times, `on_event` hook for later logging).
* **Void** reverses what the ledger says was posted for that sale (not blindly `sales.amount`): sales that predate the cash ledger (no `sale` row) change no balance; a quick sale whose amount was edited is reversed by the posted amount, so balance == ledger sum always holds.
* **PUT /sales/{id}** updates metadata. For a sale WITH items an `amount` change is 422 (the amount is the sum of the lines; enforced in the same UPDATE statement as well: `CASE WHEN EXISTS (items) THEN amount ELSE ...`). Quick sales may still change `amount`; since F4 that edit posts an `adjustment` ledger entry (see the F4 section; specs/17 #40 resolved).
* **Product delete**: the FK from `sale_items` blocks deleting a product that has been sold (error 547). *(F4: now HTTP 409, see below; specs/17 #41 resolved.)*
* Rows are scoped by `org_id` in every statement of the procedures (static test over the .sql file) and in the repository.

### Where tested
* Unit `tests/unit/test_sales_items_service.py` (fakes with the same semantics: atomic, savepoint partial, stock never negative, balance == ledger sum, org scoping, void, deadlock retry once / give up / non-deadlock not retried),
  integration `tests/integration/test_sales_items_api.py` (201/409/404/422, nothing changed after 409, void, cross-tenant, idempotent replay, back-compat quick sale), `tests/unit/test_repository_sql_shapes.py` and `test_repository_sql_rules.py` (EXEC shape, org scoping, static scan of `05_*.sql`).
* Real DB (gated `RUN_MSSQL=1`): `tests/sqlserver/test_sales_items_sqlserver.py` (commit, atomic rollback, savepoint partial, own vs nested transaction, concurrent buyers of the last unit, balance == ledger sum, void, constraints).
  Manual: `sql_server/TEST_CASES.md` F3-01..F3-12.

### Not covered / limitations
* T-SQL is unrun in the authoring sandbox. *(F4: expenses now post `expense` ledger entries, see below.)* No stock-movement history. No partial void / returns. A hot `cash_accounts` row serialises the commit of all sales of one org (fine at this scale).

## F4: Expenses on the cash ledger, Cash page, F3 follow-ups

### What
* `sql_server/06_expenses_cash.sql` (re-runnable; run 05 first, it was amended): widens `CK_cash_ledger_entry_type` with `expense_void` (guarded drop + re-create) and adds
  `dbo.usp_RecordExpense`, `dbo.usp_VoidExpense`, `dbo.usp_AdjustEntryAmount`. All three use the F3 transaction pattern (`@own_tran` own vs nested + savepoint, `XACT_ABORT ON`, `XACT_STATE()` in CATCH,
  business failures as OUTPUT values, every statement scoped by `org_id`; see specs/15).
* `05_...sql`: `usp_VoidSale` now reverses the `sale` entry PLUS its `adjustment` entries (specs/17 #51).
* Repository: `expenses_repository.record_expense` / `void_expense` (EXEC), `cash_repository.adjust_entry_amount` (EXEC), `cash_repository.list_ledger` (filters) and `get_month_summary`. The plain `create_expense` /
  `delete_expense_scoped` are GONE and the metadata `UPDATE`s of sales and expenses no longer write `amount` (they raise `ValueError` for it): there is no repository path that changes money without the ledger
  (a static test enforces: no `INSERT INTO` / `DELETE FROM` on sales, expenses, cash tables, sale_items in `repository/*.py`). `ProcedureError`, `BUSINESS_ERRORS` and the shared `call_procedure` helper moved to `repository/base.py`.
* Services: `expenses_service` (create/update/delete through the procedures, each unit of work in `run_with_deadlock_retry`), `sales_service.update_sale`, `cash_service` (validation, defaults), `products_service.delete_product` (409).
* UI: `app/(app)/cash/page.tsx` (+ sidebar "Cash"), `lib/use-cash.ts` (`useCashLedger`, `useCashSummary`), expenses/sales pages show API errors, the dashboard cash KPI links to `/cash`.

### Behaviour and why
* **Expense = three changes in one transaction**: `expenses` row, `cash_accounts.balance = balance - amount` (ONE statement, no read-then-write), `cash_ledger` row (`expense`, NEGATIVE amount, `balance_after`).
  The balance MAY become negative (a handseller can spend before cashing up; no guard, no CHECK; specs/17 #50). Invariant: `balance == SUM(ledger.amount)` per org (tested, also under concurrency).
* **Void expense** (`DELETE /expenses/{id}`): locks the expense row (`UPDLOCK, HOLDLOCK`), reverses what the ledger says was posted (`expense` + `adjustment` entries) with an `expense_void` entry, deletes the expense.
  Unknown or foreign id => `not_found` => 404. Same symmetry as sales.
* **Amount edit** (`PUT /sales|expenses/{id}` with a changed `amount`): `usp_AdjustEntryAmount` reads the CURRENT amount under an update lock (concurrent edits queue and compute their delta from the committed value), updates the amount and posts
  `delta = new - old` as an `adjustment` entry: `+delta` for a sale, `-delta` for an expense (money out grew => cash fell), updating the balance. Same amount => no entry (`unchanged`). A sale WITH line items is refused (`not_allowed` => 422):
  its amount is the sum of its items. The other fields of the same `PUT` are updated in the same request/transaction; a failure of either rolls both back.
* **`DELETE /products/{id}`**: the database's FK (`FK_sale_items_product`) already refuses; `core.db` maps a REFERENCE/FOREIGN KEY 547 to `ForeignKeyViolationError` (like 2627/2601 -> `UniqueViolationError`), `repository.base` exposes it
  as `RecordInUseError` (like `DuplicateRecordError`), the service raises `ProductInUseError` and the router answers **409** "Product has sales and cannot be deleted; deactivate it instead". `PUT {"is_active": false}` is the supported alternative.
* **`GET /cash/ledger?entry_type=&from=&to=&limit=&offset=`**: optional, parameterised, org-scoped filters (`from`/`to` inclusive, on `entry_date`); unknown `entry_type`, a `from` after `to` or a malformed date => 422.
* **`GET /cash/summary?year=&month=`** (default: current UTC month): `{year, month, opening_balance, total_in, total_out, closing_balance, by_type}`. Two scoped statements: `SUM(amount)` of everything dated before the month (opening), and
  `SUM / SUM(CASE ...) ... GROUP BY entry_type` inside the month. `total_out` is a positive magnitude, `by_type` the net per type (all five types always present), `closing = opening + total_in - total_out`. A month without rows gives zeros and
  closing == opening. Dates and caveats: specs/17 #55.

### Where tested
* Unit: `tests/unit/test_expenses_cash_service.py` (fakes mirroring the procedures: balance/ledger/delta math, negative balance, void symmetry, void after edit, item-sale refusal, cross-tenant on every verb, validation, deadlock retry, filters, summary incl. empty months),
  `test_repository_sql_shapes.py` (EXEC shapes, bound filter parameters, FK mapping vs CHECK 547), `test_repository_sql_rules.py` (org scoping of every statement in `06_*.sql`, no ledger-bypassing writes, void reverses adjustments).
* Integration: `tests/integration/test_expenses_cash_api.py` (+ `test_expenses_multitenancy.py`, `test_sales_items_api.py`): HTTP behaviour incl. 404/409/422, idempotent replay posts once.
* Real DB (gated `RUN_MSSQL=1`): `tests/sqlserver/test_expenses_cash_sqlserver.py` (atomic rollback after an overflow in the cash update, void symmetry, adjustment deltas, own vs nested transaction, concurrent expenses and concurrent adjustments keep balance == ledger sum,
  real filters/summary, product-delete 409 mapping, CHECK widening). Manual: `sql_server/TEST_CASES.md` F4-01..F4-12.

### Not covered / limitations
* T-SQL unrun in the authoring sandbox. No opening balance / back-fill of pre-ledger history (#53). No stock/cash reconciliation report. No "edit expense date" (the API always uses today for new expenses; the procedure accepts `@expense_date`).
