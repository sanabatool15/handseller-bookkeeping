# Start here: SQL Server part in plain words

The other docs (`api/specs/13`..`17`, `TEST_CASES.md`) are written as a change log for developers. This page is the short map.
It adds nothing new to the system; it only tells you which concept lives where.

## What the system is
A handseller records **sales** and **expenses**. After the SQL Server extension it also tracks **products** (with stock),
**customers**, **sale line items**, and a **cash ledger** (every money movement, with the balance after it).
Every table has `org_id`, so each business only sees its own rows.

## The 7 scripts (run in order, all re-runnable)
| File | What it creates |
|---|---|
| `01_foundation.sql` | orgs, users |
| `02_sales_expenses_agents.sql` | sales, expenses, agent jobs/logs |
| `03_products.sql` | products + stock rules |
| `04_customers.sql` | customers, link from sales |
| `05_sale_items_cash_recordsale.sql` | sale items, cash tables, `usp_RecordSale`, `usp_VoidSale` |
| `06_expenses_cash.sql` | `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount` |
| `07_txn_log.sql` | transaction event log (Activity page) |

## Concept -> where to see it -> test cases
| Concept | Where in code | Test cases (`TEST_CASES.md`) |
|---|---|---|
| Constraints (CHECK, UNIQUE, FK) | `02`, `03`, `04` | F0b-02, F1-02, F1-03, F2-03, F3-09 |
| Triggers (`updated_at`) | every table | F0a-04, F1-04, F2-04 |
| Stored procedure | `usp_RecordSale` in `05` | F3-02 |
| Commit / rollback (atomicity) | `usp_RecordSale` | F3-02, F3-03 |
| Savepoint | `sp_item` inside `usp_RecordSale` | F3-04 |
| Nested transaction | `@own_tran` in each procedure | F3-06, F4-05 |
| Race condition / isolation | guarded `UPDATE ... WHERE stock_qty >= @qty` | F3-07, F1-08, F5-08, F5-09, F5-11 |
| Deadlock | DB Lab, retry in `core/db.py` | F5-10 |
| Cash ledger | `cash_accounts`, `cash_ledger` | F3-10, F4-02, F4-07 |
| Void / adjust | `usp_VoidSale`, `usp_AdjustEntryAmount` | F3-08, F4-06..F4-09 |
| Activity log | `07`, Activity page | F5-03..F5-06 |

## How to read a test case code
`F3-02` = slice **F3**, case **02**. Slices are just the order the work was built in:
F0 foundation, F1 products, F2 customers, F3 sale items + cash, F4 expenses on the ledger, F5 activity log + DB Lab.
Cases that say "API" go through the app; the rest are pure SSMS queries.

## Where the Python tests are
`api/tests/sqlserver/` has one file per area (products, customers, sales items, expenses/cash, ledger, txn log, register).
They run the same checks as the manual cases automatically (`RUN_MSSQL=1 pytest tests/sqlserver -v`).
