# SQL Server test cases (manual, SSMS)

Run scripts in order. Replace nothing unless noted. All T-SQL is untested at authoring time.

## Slice F0a: foundation + auth

### F0a-01 Script runs and is re-runnable
Steps: open `01_foundation.sql` in SSMS, Execute. Execute it a second time.
Expected: both runs finish without errors; database `HandsellerDB` exists with tables `orgs`, `users`.
Pass: no error messages; `SELECT name FROM sys.tables` lists both.

### F0a-02 Constraints and index
Steps: `SELECT name FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.users');` and
`SELECT name FROM sys.foreign_keys;`
Expected: `UQ_users_email`, `idx_users_org_id`, `FK_users_org`, `FK_orgs_owner` present.
Pass: all four listed.

### F0a-03 Unique email
Steps: `INSERT users(email,hashed_password) VALUES(N'a@x.com',N'h'); INSERT users(email,hashed_password) VALUES(N'A@X.COM',N'h');`
Expected: second insert fails with error 2627 (case-insensitive collation).
Pass: error 2627; one row. Cleanup: `DELETE users WHERE email=N'a@x.com'`.

### F0a-04 updated_at trigger
Steps: insert a user; `WAITFOR DELAY '00:00:01'`; `UPDATE users SET full_name=N'B' WHERE email=N'a@x.com'`; select `created_at, updated_at`.
Expected: `updated_at` > `created_at`.
Pass: yes. Same check for `orgs` (update `name`).

### F0a-05 Register via API
Steps: start `uvicorn core.fastapi_app:app`; `POST /auth/register` with `Idempotency-Key` header and
`{"email":"o@x.com","password":"hunter2pass","org_name":"Acme"}`.
Expected: 201 with `access_token`, `user.org_id == org.id`, `org.owner_id == user.id`.
Pass: and `SELECT * FROM users/orgs` shows the linked rows.

### F0a-06 Duplicate email
Steps: repeat F0a-05 with a new Idempotency-Key.
Expected: 409 `Email already registered`; still exactly one user and one org for that email.

### F0a-07 Atomic rollback
Steps: in SSMS, `ALTER TABLE orgs ADD CONSTRAINT CK_tmp CHECK (name <> N'FAIL');` then register with `org_name` = `FAIL`.
Expected: 500; `SELECT * FROM users WHERE email=...` returns no row (no orphan user). Cleanup: `ALTER TABLE orgs DROP CONSTRAINT CK_tmp;`.

### F0a-08 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver -v` from `api/`. Pass: 3 passed.

## Slice F0b: sales, expenses, agent jobs/logs (script `02_sales_expenses_agents.sql`)

Prerequisite: `01_foundation.sql` applied. Below, `<ORG>` / `<USER>` are the ids from `POST /auth/register`
(or `SELECT id, org_id FROM users WHERE email = ...`). Send an `Idempotency-Key` header on every POST/PUT.

### F0b-01 Script runs and is re-runnable
Steps: execute `02_sales_expenses_agents.sql` in SSMS, then execute it again.
Expected: no errors either time; tables `sales`, `expenses`, `agent_jobs`, `agent_logs` exist.
Pass: `SELECT name FROM sys.tables ORDER BY name` lists all six tables (with `orgs`, `users`).

### F0b-02 Indexes, constraints, triggers
Steps: `SELECT name FROM sys.indexes WHERE name LIKE 'idx[_]%' ORDER BY name;`
`SELECT name FROM sys.check_constraints ORDER BY name;` `SELECT name FROM sys.triggers ORDER BY name;`
Expected: `idx_sales_org_id, idx_expenses_org_id, idx_agent_jobs_org_id, idx_agent_logs_job_id, idx_agent_logs_org_id, idx_users_org_id`;
checks `CK_agent_jobs_status, CK_agent_jobs_input_json, CK_agent_jobs_result_json, CK_agent_jobs_error_json, CK_agent_logs_insights_json`;
triggers `trg_sales_updated_at, trg_expenses_updated_at, trg_agent_jobs_updated_at, trg_agent_logs_updated_at` (+ the two from F0a).
Pass: all listed.

### F0b-03 updated_at triggers
Steps: insert a sale (`INSERT sales(org_id, amount) VALUES (<ORG>, 10)`), `WAITFOR DELAY '00:00:01'`,
`UPDATE sales SET category = N'x' WHERE org_id = <ORG>`; compare `created_at`, `updated_at`. Repeat for `expenses`, `agent_jobs`
(`job_name`), `agent_logs` (`step_name`).
Expected: `updated_at` > `created_at` in every case. Pass: yes.

### F0b-04 JSON and status checks
Steps: `INSERT agent_jobs(job_name, org_id, input_payload) VALUES (N'x', <ORG>, N'not json');`
and `INSERT agent_jobs(job_name, org_id, status) VALUES (N'x', <ORG>, N'bogus');`
Expected: both fail (check constraint violation, error 547). `input_payload = NULL` and `N'{}'` insert fine.
Pass: two errors; no rows inserted by the failing statements.

### F0b-05 agent_logs cannot disagree with its job's org
Steps: create two orgs A, B and a job of A; `INSERT agent_logs(job_id, org_id, step_name) VALUES (<jobA>, <ORG_B>, N's');`
Expected: FK violation (error 547, composite FK `FK_agent_logs_job`). Same insert with `<ORG_A>` succeeds. Deleting the job deletes its logs (cascade).
Pass: as described.

### F0b-06 Create sale/expense via API (JSON shape)
Steps: `POST /sales {"amount": 19.99, "category": "retail", "customer_name": "Zed"}`; `POST /expenses {"amount": 5.25, "category": "rent", "voucher_reference": "V-1"}`.
Expected: 201; `id`, `org_id`, `created_by` strings; `amount` a JSON number (19.99); `sale_date`/`expense_date` = today (UTC) as `YYYY-MM-DD`;
`created_at`/`updated_at` ISO strings. `GET /sales`, `/sales/{id}`, `/expenses` return the same shapes (compare with `lib/types.ts` `LedgerEntry`).
Pass: yes, and `SELECT * FROM sales` shows the row with `org_id = <ORG>`, `created_by = <USER>`.

### F0b-07 Update, delete, validation
Steps: `PUT /sales/{id} {"amount": 20.5}`; `DELETE /sales/{id}`; `POST /sales {"amount": 0}`; `POST /sales` without `amount`.
Expected: 200 with the new amount (other fields unchanged; note `updated_at` in the PUT response is the pre-trigger value, a later GET shows the new one);
204 then 404 on GET; 422; 422.
Pass: yes.

### F0b-08 Tenant isolation => 404
Steps: register a second org B (token B). With token B call `GET/PUT/DELETE /sales/{id of A's sale}` and the same for `/expenses/{id}` and `GET /agent-jobs/{A's job}`.
Expected: always 404 (never 403/200); A's rows unchanged; `GET /sales` with token B returns `[]`.
Pass: yes.

### F0b-09 Month sums and breakdown are computed in SQL
Steps: insert sales for org `<ORG>` with `sale_date` 2026-01-31, 2026-02-01, 2026-02-28, 2026-03-01 (amounts 7, 100.10, 50.20, 9; category retail) and one 2026-02-10 gift sale of 1.0;
then `SELECT COALESCE(SUM(amount),0) FROM sales WHERE org_id=<ORG> AND sale_date >= '2026-02-01' AND sale_date < '2026-03-01';` (expect 151.30).
In Python (from `api/`): `python -c "from core.clients import db_session; from services.financial_report_service import monthly_summary, sales_breakdown_by_category as b; \
s=db_session().__enter__(); print(monthly_summary(s, org_id='<ORG>', year=2026, month=2), b(s, org_id='<ORG>', year=2026, month=2))"`.
Expected: `total_sales` 151.3 and `{'retail': 150.3, 'gifts': 1.0}`; month 4 gives 0.0; `year=2026, month=12` works (range ends 2027-01-01).
Pass: matches the SQL result; boundary days (Jan 31, Mar 1) excluded.

### F0b-10 Agent job lifecycle through the API
Steps: with Inngest dev server running (or without it: the job just stays pending), `POST /agent-jobs/financial-advice {"question": "How are we doing?"}`; then poll `GET /agent-jobs/{job_id}`.
Expected: 202 with `job_id`, `status: "pending"`; the row is already committed when the response returns; `input_payload` is the dict `{"question": ...}`;
with the worker running: `status` becomes `processing` then `completed`, `result` is a dict with `advice` and `source`, and `SELECT step_name FROM agent_logs WHERE job_id = ...` shows `gather_data, run_agent, finalize`.
Pass: yes (without OpenAI keys `source` is `rule_based_fallback`).

### F0b-11 MCP server
Steps: from `api/`, `python mcp_gateway/server.py` and connect a client (or call the tools from a unit harness): `log_sale`, `log_expense`, `trigger_financial_agent_job`, `stream_job_logs`, read `ledger://<ORG>/monthly.csv`.
Expected: rows appear in `sales`/`expenses`; logs of a job of another org come back empty with an error log ("not found"); CSV lists only the current month.
Pass: yes.

### F0b-12 Health
Steps: `GET /health` with SQL Server up, then stop the SQL Server service (or break `MSSQL_*`) and call again.
Expected: first `{"status":"ok","checks":{"redis":"ok","database":"ok"}}`; second `database` = `error: ...` (status field stays "ok"); startup log shows "SQL Server connection OK" / a warning.
Pass: yes.

### F0b-13 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver -v` from `api/`.
Expected: 3 tests from F0a + 8 from F0b (`test_ledger_sqlserver.py`) pass (11 total).
Pass: all green; tests clean up their own orgs/users (`mssql-test-*`).

## Slice F1: products & stock

Requires `03_products.sql` (run after 01 and 02). `<ORG>`/`<ORG_B>` = ids of two registered orgs, `<USER>` a user of `<ORG>`.

### F1-01 Script runs and is re-runnable
Steps: open `03_products.sql` in SSMS, Execute, Execute again.
Expected: no errors either time; `SELECT name FROM sys.tables WHERE name='products'` returns a row;
`SELECT name FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.products')` lists `PK_products`, `UQ_products_org_sku`, `idx_products_org_id`;
`SELECT name FROM sys.triggers` lists `trg_products_updated_at`.
Pass: all present.

### F1-02 CHECK constraints (stock, price, reorder level)
Steps: `INSERT products(org_id,name,sku,price,stock_qty) VALUES(<ORG>,N'a',N'S1',1,-1);`, then `...price=-1...`, then `...,reorder_level) ... -1`.
Also insert a valid row (`stock_qty=5`) and `UPDATE products SET stock_qty = -1 WHERE sku=N'S1' AND org_id=<ORG>`.
Expected: each bad statement fails with error 547 (`CK_products_stock_qty` / `CK_products_price` / `CK_products_reorder_level`); the row keeps stock 5.
Pass: four 547 errors; no negative values in the table.

### F1-03 Unique SKU per org
Steps: insert `(<ORG>, N'a', N'DUP', 1)` twice; then insert `(<ORG_B>, N'a', N'DUP', 1)`.
Expected: second insert fails with 2627 (`UQ_products_org_sku`); the insert for `<ORG_B>` succeeds. Collation is case-insensitive: `N'dup'` in `<ORG>` also fails.
Pass: as described.

### F1-04 updated_at trigger
Steps: insert a product; `WAITFOR DELAY '00:00:01'`; `UPDATE products SET name=N'b' WHERE sku=N'S1' AND org_id=<ORG>`; select `created_at, updated_at`.
Expected: `updated_at` > `created_at`. Pass: yes.

### F1-05 Create / list / get / update / delete via API (JSON shape)
Steps: `POST /products {"name":"Mug","sku":"MUG-1","price":12.5,"stock_qty":4,"reorder_level":2}` with `Idempotency-Key`; then `GET /products`, `GET /products/{id}`,
`PUT /products/{id} {"price": 15, "is_active": false}`, `DELETE /products/{id}`.
Expected: 201; `id`/`org_id`/`created_by` strings; `price` a JSON number (12.5), `stock_qty`/`reorder_level` integers, `is_active` a boolean (not 0/1),
`created_at`/`updated_at` ISO strings; PUT keeps `stock_qty` unchanged (note: `updated_at` in the PUT response is pre-trigger); DELETE 204 then GET 404.
Pass: yes, and `SELECT * FROM products` shows the row with `org_id = <ORG>`, `created_by = <USER>`.

### F1-06 Validation => 422, duplicate => 409
Steps: `POST /products` with empty `name`, empty `sku`, `price: -1`, `reorder_level: -1`, `stock_qty: -1`; post the same SKU twice; `PUT` a product's `sku` to another product's SKU.
Expected: 422 for each invalid body; 409 `SKU 'MUG-1' already exists` for the duplicate create and for the clashing PUT; the same SKU as another org is accepted (201).
Pass: yes.

### F1-07 Adjust stock: success, insufficient (409), not found (404)
Steps: product with stock 5: `POST /products/{id}/adjust-stock {"delta": 3, "reason": "restock"}`; `{"delta": -8}`; `{"delta": -1}`; `{"delta": 0}`; unknown id.
Expected: 200 stock 8; 200 stock 0 (exactly to zero is allowed); 409 "Insufficient stock..."; 422 (zero delta); 404. Stock stays 0 after the 409.
Pass: yes. (`reason` is accepted but not stored yet: specs/17.)

### F1-08 Adjust stock is race-safe
Steps: product with stock 9. From two SSMS windows (or `RUN_MSSQL=1 pytest tests/sqlserver/test_products_sqlserver.py -k race`), run concurrently the statement
`UPDATE products SET stock_qty = stock_qty + -1 WHERE id=<ID> AND org_id=<ORG> AND stock_qty + -1 >= 0;` repeatedly (12 times in total across sessions).
Expected: exactly 9 statements report 1 row affected, 3 report 0; final `stock_qty` = 0, never negative.
Pass: yes (the pytest version asserts this with 12 threads).

### F1-09 Low-stock filter
Steps: products (stock/reorder) 1/2, 2/2, 3/2; `GET /products?low_stock=true`.
Expected: only the first two (stock <= reorder level); `GET /products` returns all three, ordered by name.
Pass: yes.

### F1-10 Tenant isolation => 404
Steps: with org B's token call `GET/PUT/DELETE /products/{A's id}` and `POST /products/{A's id}/adjust-stock {"delta": 1}` and `{"delta": -1}`; `GET /products`.
Expected: always 404 (never 403/200/409); A's product unchanged; B's list is `[]`.
Pass: yes.

### F1-11 Missing Idempotency-Key and replay
Steps: `POST /products` and `POST .../adjust-stock` without the header; then `adjust-stock {"delta": 5}` twice with the SAME key.
Expected: 400 for missing key; the replay returns the cached response and stock only increases by 5 once.
Pass: yes.

### F1-12 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver/test_products_sqlserver.py -v` from `api/`.
Expected: 6 tests pass (constraints, unique-per-org, JSON shape/trigger, isolation, adjust edge cases, 12-thread race).
Pass: all green; tests clean up their own orgs/users/products.


## Slice F2: customers (`04_customers.sql`)

Requires 01..04 applied. Replace `<ORG>`, `<ORG2>` (two orgs), `<ID>` with real GUIDs.

### F2-01 Script runs and is re-runnable
Steps: execute `04_customers.sql` in SSMS; execute it a second time.
Expected: no errors either time. `customers` exists; `sales.customer_id` exists exactly once.
Pass: `SELECT COL_LENGTH('dbo.sales','customer_id');` is not NULL; second run changes nothing (also with a sales table that already has the column).

### F2-02 Indexes, FK, trigger
Steps: `SELECT name, is_unique, filter_definition FROM sys.indexes WHERE object_id IN (OBJECT_ID('dbo.customers'), OBJECT_ID('dbo.sales'));`, `SELECT name FROM sys.foreign_keys WHERE name='FK_sales_customer';`, `SELECT name FROM sys.triggers WHERE name='trg_customers_updated_at';`
Expected: `idx_customers_org_id`, `UQ_customers_org_phone` (unique, filter `([phone] IS NOT NULL)`), `UQ_customers_id_org`, `idx_sales_org_customer`, the FK and the trigger exist.
Pass: all present.

### F2-03 Filtered unique phone per org
Steps: insert `(org <ORG>, name 'A', phone '555')` twice; then insert `(<ORG2>, 'B', '555')`; then insert three customers in `<ORG>` with `phone NULL`.
Expected: the second insert fails with error 2601 (unique index); the `<ORG2>` insert works; all NULL-phone inserts work (a plain UNIQUE would allow only one NULL).
Pass: yes. API: `POST /customers` twice with the same phone => 409; blank phone `""` is stored as NULL.

### F2-04 updated_at trigger
Steps: insert a customer, `WAITFOR DELAY '00:00:01'`, `UPDATE customers SET notes=N'x' WHERE id=<ID>`, select `created_at, updated_at`.
Expected: `updated_at` > `created_at`.
Pass: yes.

### F2-05 CRUD via API and validation
Steps: `POST /customers {"name":"Ana","phone":"555","email":"a@x.com"}` (201); `GET /customers`; `GET/PUT /customers/{id}`; `PUT {"phone": null}` clears the phone; `POST` with `{"name":""}`, `{"name":"x","email":"nope"}`, a 201-char name.
Expected: 201/200 with the row; phone `null` after the clear and other fields untouched; the invalid bodies give 422.
Pass: yes.

### F2-06 Search `?q=` (prefix on name or phone, wildcards literal)
Steps: customers `Anna`(phone 100), `Annabel`, `Bob`(phone `1%0`), `a_b`, `axb`; call `GET /customers?q=ann`, `?q=10`, `?q=1%25`, `?q=%25`, `?q=_`, `?q=a_`.
Expected: `[Anna, Annabel]`; `[Anna]`; `[Bob]`; `[]`; `[]`; `[a_b]` (`%`, `_`, `[` are escaped, never wildcards).
Pass: yes.

### F2-07 Sale with customer_id
Steps: `POST /sales {"amount":10,"customer_id":"<ID>","customer_name":"walk-in"}`; `POST /sales {"amount":5}`; `GET /sales/{id}`.
Expected: 201 with `customer_id` = `<ID>` and `customer_name` unchanged; the second sale has `customer_id: null`.
Pass: yes. `SELECT customer_id FROM sales WHERE id=...` matches.

### F2-08 Foreign / unknown customer on a sale => 404
Steps: with org B's token `POST /sales {"amount":5,"customer_id":"<ORG A customer id>"}` and with a random GUID; `PUT /sales/{B sale} {"customer_id":"<A's id>"}`.
Expected: all three 404 `{"detail":"Customer not found"}` (identical to the random-GUID answer), no sale created/changed. Direct SQL `INSERT INTO sales(org_id,amount,customer_id) VALUES(<ORG2>,1,<ORG A customer>)` fails with error 547 (composite FK).
Pass: yes.

### F2-09 Summary
Steps: customer with sales 10.25 and 5 (plus another customer's sale and a sale without customer): `GET /customers/{id}/summary`; then for a customer without sales.
Expected: `{"customer":{...},"total_sales":15.25,"sale_count":2,"last_sale_date":"<date>"}`; `0 / 0 / null` for the empty one. Compare with `SELECT SUM(amount),COUNT(*),MAX(sale_date) FROM sales WHERE customer_id=<ID> AND org_id=<ORG>`.
Pass: numbers equal.

### F2-10 Delete behaviour (409 while sales exist)
Steps: `DELETE /customers/{id}` for a customer with sales; then `PUT /sales/{sale} {"customer_id": null}` for each sale; `DELETE` again; `DELETE` once more.
Expected: 409 "Customer has sales..." (customer and its sales untouched); sales then show `customer_id: null`; DELETE 204; last DELETE 404.
Pass: yes. The delete is ONE statement with `NOT EXISTS (SELECT 1 FROM sales ...)`; FK_sales_customer is the backstop for a concurrent sale.

### F2-11 Tenant isolation => 404
Steps: org B's token: `GET/PUT/DELETE /customers/{A's id}`, `GET /customers/{A's id}/summary`, `GET /customers`, `GET /customers?q=<A's name>`.
Expected: 404 for the by-id calls (also DELETE of an A customer that has sales: 404, not 409); lists are `[]`.
Pass: yes.

### F2-12 Idempotency
Steps: `POST /customers` and `PUT /customers/{id}` without `Idempotency-Key`; then the same POST twice with one key.
Expected: 400 for missing key; the replay returns the same body and only one customer exists.
Pass: yes.

### F2-13 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver/test_customers_sqlserver.py -v` from `api/`.
Expected: 5 tests pass (summary join/scoping, filtered unique index, delete behaviour, composite FK, literal wildcards + trigger + isolation).
Pass: all green; tests clean up their own rows.

## Slice F3: sale line items, cash ledger, usp_RecordSale / usp_VoidSale

Run `05_sale_items_cash_recordsale.sql` after 01..04 (twice, to check it is re-runnable). Replace `<ORG>` / `<USER>` with ids from your `orgs` / `users`.
Helper setup used below (run once in SSMS):
```sql
DECLARE @org uniqueidentifier = '<ORG>';
INSERT products (org_id, name, sku, price, stock_qty) VALUES (@org, N'Mug', N'F3-MUG', 10.00, 5), (@org, N'Pen', N'F3-PEN', 2.50, 1);
SELECT id, name, stock_qty FROM products WHERE org_id = @org AND sku LIKE N'F3-%';
```

### F3-01 Script is re-runnable; objects exist
Steps: run the script twice; `SELECT name FROM sys.tables WHERE name IN ('sale_items','cash_accounts','cash_ledger'); SELECT name FROM sys.procedures WHERE name LIKE 'usp[_]%Sale';`
Expected: no errors both times; 3 tables and `usp_RecordSale`, `usp_VoidSale` listed. `sys.key_constraints` has `UQ_sales_id_org`, `UQ_products_id_org`.
Pass: yes.

### F3-02 Procedure commit (own transaction, from SSMS)
Steps (no `BEGIN TRAN` first, so the procedure owns the transaction):
```sql
DECLARE @sale uniqueidentifier, @total decimal(14,2), @status nvarchar(20), @msg nvarchar(400), @err int, @skipped nvarchar(max);
DECLARE @items nvarchar(max) = N'[{"product_id":"<MUG_ID>","quantity":2},{"product_id":"<PEN_ID>","quantity":1,"unit_price":3}]';
EXEC dbo.usp_RecordSale @org_id='<ORG>', @created_by='<USER>', @category=N'retail', @items=@items,
     @sale_id=@sale OUTPUT, @total=@total OUTPUT, @status=@status OUTPUT, @message=@msg OUTPUT, @error_number=@err OUTPUT, @skipped_items=@skipped OUTPUT;
SELECT @sale, @total, @status, @msg, @err, @@TRANCOUNT AS trancount_after;
```
Expected: `@total` 23.00 (2*10 + 1*3), status `committed`, `@err` NULL, `trancount_after` 0. Mug stock 3, Pen stock 0; one `sale_items` row per line with `line_total` 20.00 / 3.00; `cash_accounts.balance` 23.00; one `cash_ledger` row (`sale`, amount 23.00, balance_after 23.00, ref_id = @sale).
Pass: all numbers match.

### F3-03 Atomic rollback on insufficient stock
Steps: call the procedure with `[{"product_id":"<MUG_ID>","quantity":1},{"product_id":"<PEN_ID>","quantity":5}]` (Pen has 0 left now).
Expected: `@status = 'rolled_back'`, `@err = 50001`, message `Not enough stock for Pen`, `@sale` NULL. Mug stock unchanged (3), no new `sales` / `sale_items` / `cash_ledger` row, balance unchanged (23.00).
Pass: nothing changed, not even the first (valid) item.

### F3-04 Savepoint partial (`@skip_invalid_items = 1`)
Steps: same call with `@skip_invalid_items = 1` and an extra item with a random `product_id`.
Expected: `@status = 'partial'`, `@skipped` is a JSON array with two entries (50001 for Pen, 50002 unknown product); only the Mug line exists, Mug stock decreased by 1, balance increased by 10.00.
Pass: yes. With ONLY invalid items and skip=1: `rolled_back`, nothing recorded.

### F3-05 Quick sale (no items)
Steps: `EXEC dbo.usp_RecordSale @org_id='<ORG>', @created_by='<USER>', @amount=40, @category=N'retail', ...outputs`; then with `@amount = NULL` and no items.
Expected: first `committed`, total 40, balance +40, ledger row; second `rolled_back`, `@err = 50003`.
Pass: yes.

### F3-06 Nested transaction: the caller decides
Steps: `BEGIN TRAN; EXEC dbo.usp_RecordSale ...(valid items)...; SELECT @@TRANCOUNT; ROLLBACK;`
Expected: status `committed`, `@@TRANCOUNT` = 1 inside (the procedure did NOT commit); after `ROLLBACK` stock, sales, ledger and balance are exactly as before. Repeat with `COMMIT` instead: the data stays.
Then `BEGIN TRAN; <insert one unrelated row>; EXEC ... (insufficient stock) ...; SELECT @@TRANCOUNT; COMMIT;` => status `rolled_back`, `@@TRANCOUNT` still 1, the unrelated row survives the commit.
Pass: yes (this proves the savepoint logic).

### F3-07 Race: two sessions, one unit
Steps: product with `stock_qty = 1`. Session A: `BEGIN TRAN; EXEC usp_RecordSale ... qty 1 ...;` (do not commit). Session B: run the same EXEC (it blocks on the product row). In A: `COMMIT`.
Expected: B unblocks and returns `rolled_back` / 50001; stock = 0; exactly one sale; balance = one sale.
Pass: yes. Automated version: `RUN_MSSQL=1 pytest tests/sqlserver/test_sales_items_sqlserver.py -k race -v` (10 threads, 1 unit => exactly 1 success).

### F3-08 Void
Steps: `EXEC dbo.usp_VoidSale @org_id='<ORG>', @sale_id=@sale, @voided_by='<USER>', @status=@s OUTPUT, @message=@m OUTPUT, @error_number=@e OUTPUT;`
Expected: `voided`; the stock of each item is back, a `sale_void` ledger row with the negative amount, balance reduced by the sale total, the sale and its items are gone. Again with the same id: `not_found` / 50006. With another org's id: `not_found`, nothing changed.
Pass: yes.

### F3-09 Constraints work without the procedure
Steps: `INSERT sale_items (org_id,sale_id,product_id,quantity,unit_price) VALUES (...)` with quantity 0; with unit_price -1; with a product of ANOTHER org; `INSERT cash_ledger (org_id,entry_type,amount,balance_after) VALUES ('<ORG>',N'bogus',1,1)`; `UPDATE products SET stock_qty=-1 ...`.
Expected: every statement fails (547, composite FK / CHECK).
Pass: yes.

### F3-10 API: POST /sales with items, then GET /cash/balance
Steps: `POST /sales {"category":"retail","items":[{"product_id":"<MUG_ID>","quantity":2}]}` with `Idempotency-Key`; `GET /products/<MUG_ID>`; `GET /cash/balance`; `GET /cash/ledger`.
Expected: 201 with `items` (product_name, unit_price 10, line_total 20), `amount` 20; stock decreased by 2; balance +20; one ledger entry.
Pass: yes. Repeating the POST with the same key returns the same body and sells only once.

### F3-11 API error mapping and no side effects
Steps: `POST /sales` with quantity larger than stock; with an unknown/other org product id; with `quantity: 0`; with neither `amount` nor `items`; `skip_invalid_items: true` mixed valid/invalid.
Expected: 409 `Not enough stock for <name>`; 404 `Product not found`; 422; 422; 201 with `skipped_items`. After each failure the stock, sales list and balance are unchanged.
Pass: yes. `PUT /sales/{id}` with `amount` on an item sale: 422; `DELETE /sales/{id}` voids (stock/balance restored), other org's token: 404.

### F3-12 Automated DB tests
Steps: `RUN_MSSQL=1 pytest tests/sqlserver/test_sales_items_sqlserver.py -v` from `api/`.
Expected: 10 tests pass (commit, atomic rollback, savepoint partial, own vs nested transaction, nested business failure, 2 race tests, void, plain sale + foreign product, constraints).
Pass: all green; tests clean up their own rows. If the engine reports a syntax error in the procedures, fix it in `05_...sql` and re-run (the script is re-runnable); please report the message so the spec can be corrected.
