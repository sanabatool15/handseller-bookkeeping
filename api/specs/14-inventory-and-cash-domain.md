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
* No stock-movement history: `reason` on adjust-stock is validated but not stored. No link from sales to products yet (later slice).
* Hard delete only; once sales reference products, deletion must become soft (`is_active = 0`) or be blocked by FK.
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
