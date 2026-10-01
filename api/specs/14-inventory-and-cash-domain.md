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
