# UI extensions (Products, Customers, Cash, Activity, DB Lab)

What each page is for, which API it uses, and where it is tested. Next.js pages live under `app/(app)/<name>/page.tsx`, hooks in `lib/use-*.ts`, shared types in `lib/types.ts`, the navigation in `components/layout/sidebar.tsx`.
There is no browser test framework in the project: pages are verified by `npm run lint` + `npm run build` (type-checks them) and by the manual steps in `sql_server/TEST_CASES.md`; the APIs behind them are covered by backend tests.

| Page | Slice | What / why | API | Tests |
|---|---|---|---|---|
| Products `/products` | F1 | List with client-side search (name/SKU), a low-stock KPI and badge, create, edit, delete (409 when the product has sales: deactivate instead), adjust stock (+/- with a reason). Why: stock is the inventory that sales consume (specs/14). | `/products`, `/products/{id}/adjust-stock` | `tests/integration/test_products_api.py`, `tests/unit/test_products_service.py`, `tests/sqlserver/test_products_sqlserver.py`, TEST_CASES F1-xx |
| Customers `/customers` | F2 | List with prefix search, create/edit/delete, per-customer summary (total sales, count, last sale). Why: sales can be linked to a customer (`customer_id`). Delete with sales -> 409. | `/customers`, `/customers/{id}/summary` | `test_customers_api.py`, `test_customers_service.py`, `test_customers_sqlserver.py`, F2-xx |
| Cash `/cash` | F4 | Balance, monthly summary cards (opening, money in/out, closing), type/date filters, ledger with running balance. Why: shows that sales/expenses/voids/adjustments really move cash (ACID demo). Balance may be negative. | `/cash/balance`, `/cash/ledger`, `/cash/summary` | `test_expenses_cash_api.py`, `test_expenses_cash_service.py`, `test_expenses_cash_sqlserver.py`, F4-xx |
| Activity `/activity` | F5 | The live transaction log: one row per request (time, request id, operation, outcome badge, retries, duration, isolation level), filters (request id, operation, outcome), auto-refresh toggle (3 s), click a request id for its event timeline (+ms offsets, messages). | `/db-logs/requests`, `/db-logs` | `test_txn_log_api.py`, `test_txn_recorder.py`, `test_txn_log_sqlserver.py`, F5-xx |
| DB Lab `/db-lab` | F5 | Demo-only controls (product, second product, clients, quantity, race mode, isolation level, delay) and three buttons: **Race sale**, **Force deadlock**, **Deadlock fixed**; per-client results table, before/after stock, verdict, link from every client to its Activity timeline. | `/db-lab/status`, `/db-lab/race-sale`, `/db-lab/deadlock`, `/db-lab/deadlock-fixed` | `test_db_lab_api.py`, `test_txn_log_sqlserver.py`, F5-xx |

## Activity page (F5)
* Outcome badges: `committed` (green), `deadlock, retried` (accent: committed after >= 1 retry), `rolled back` (red), `rejected (business rule)` (grey: a business rule such as insufficient stock refused it; NOT an engine rollback), `in progress`.
* The timeline labels each step in words. `lock_wait_suspected` is shown as "Lock wait suspected (inferred from elapsed time, not observed)": the application only measures how long a call took and cannot observe lock waits (specs/15 section 8). Do not reword this into a claim that a lock wait was observed.
* `/activity?request_id=<id>` opens the page filtered and with the timeline open (the DB Lab links there).
* The log is written after the transaction ended on a separate connection, so rolled-back and rejected requests appear too. Reads and uninstrumented writes do not appear.

## DB Lab page (F5)
* Shown in the sidebar and functional only when `GET /db-lab/status` returns `{"enabled": true}` (server setting `ENABLE_DB_LAB`, default false). When off the page says so and every other lab route is 404. The status call is the only lab route that never 404s; a failing status call counts as "off".
* Labelled **demo only**: it runs real concurrent transactions on the user's own products and restores the stock afterwards (specs/15 section 9). It must not be enabled for real users.
* A run blocks for several seconds (WAITFOR + up to ~5 s for SQL Server to detect a deadlock); buttons are disabled meanwhile.
* The results table shows per client: outcome (`committed`, `rejected` = business rule, `rolled back` = engine error), retries, duration, the SQL Server error it met (1205 even when the retry then committed), message and a link to its timeline. The explanatory note under the table repeats that lock waits are inferred.
* Suggested demo (also TEST_CASES F5-07..F5-10): Race sale on a product with stock 1, mode `unsafe`, READ COMMITTED, 3 clients => 3 committed, "OVERSOLD"; same with `safe` => 1 committed, 2 rejected; `unsafe` + SERIALIZABLE => one deadlock victim retried, no oversell; Force deadlock => one client shows 1205 and retries 1; Deadlock fixed => no victim.

## Navigation
`Activity` is always in the sidebar. `DB Lab` is added only when the status call said enabled (the sidebar asks once when it mounts).
