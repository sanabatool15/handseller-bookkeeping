# Transactions and concurrency (slice F3 onward)

Course topic: ACID. This page explains WHERE transactions begin and end in this system, how the request-level
transaction and the stored procedures' own transaction logic fit together, and how concurrent sales stay correct.
T-SQL referenced here is in `sql_server/05_sale_items_cash_recordsale.sql` and `sql_server/06_expenses_cash.sql` and has not been executed in the authoring sandbox (specs/17 #43).

## 1. Who owns the transaction?

| Layer | What it does |
|---|---|
| `routers/deps.py::get_db` | One pyodbc connection per HTTP request, `autocommit=False`. After the handler returns it calls `commit()`; on an exception `rollback()`; always `close()`. |
| `core/db.py::Db` | `commit()` / `rollback()` are pyodbc's. `transaction(db)` (used by `register`) = commit on success, rollback on error. |
| Stored procedures | `usp_RecordSale`, `usp_VoidSale` (F3) and `usp_RecordExpense`, `usp_VoidExpense`, `usp_AdjustEntryAmount` (F4) contain their own `BEGIN TRANSACTION` / `SAVE TRANSACTION`, `COMMIT`, `ROLLBACK` logic. |
| Services | Never run SQL, never call `commit()` themselves, except `auth_service.register` (explicit `transaction`). They wrap repository calls in `run_with_deadlock_retry`. |

### What "autocommit off" means on SQL Server
pyodbc with `autocommit=False` makes the ODBC driver run the connection with `SET IMPLICIT_TRANSACTIONS ON`: the first data statement
(`SELECT`, `INSERT`, `UPDATE`, ...) silently starts a transaction (`@@TRANCOUNT = 1`) that stays open until `commit()` / `rollback()`.
So a request that first reads something (for example the customer ownership check in `create_sale`) is ALREADY inside a transaction when it executes the procedure.

## 2. Nested `@@TRANCOUNT`: why the procedure must not blindly `BEGIN TRAN ... COMMIT`
* `BEGIN TRAN` inside an open transaction only increments `@@TRANCOUNT` (2). `COMMIT` then only decrements it (1): NOTHING is durable until the OUTERMOST commit.
* `ROLLBACK TRAN` (without a name) rolls back EVERYTHING to the outermost level and sets `@@TRANCOUNT = 0`: it would silently undo the caller's earlier work too, and a later `COMMIT` by the caller then fails with error 3902.
* A named savepoint (`SAVE TRANSACTION sp`) can be rolled back to (`ROLLBACK TRANSACTION sp`) without touching anything before it and without changing the outer transaction's fate.

### The chosen approach (both procedures)
At the very top, before any table access:
```
DECLARE @own_tran bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;
```
* `@own_tran = 1` (called from SSMS or a fresh connection): `BEGIN TRANSACTION` ... `COMMIT TRANSACTION`; failure => `ROLLBACK TRANSACTION`. The procedure is durable when it returns.
* `@own_tran = 0` (called inside the request's implicit transaction): `SAVE TRANSACTION sp_record_sale`; NO commit (the caller owns it; `get_db` commits after the handler);
  failure => `ROLLBACK TRANSACTION sp_record_sale`, which undoes only the procedure's work and leaves the caller's transaction usable.
* Why `@own_tran` is computed first: under implicit transactions the first `SELECT` would open a transaction and make the answer "nested" even though we started clean.
  That is also why the procedure does its table validations only AFTER the transaction/savepoint has been opened.
* Result: no double commit and no broken `@@TRANCOUNT`, whichever way the procedure is called. The repository does not call `commit()`; `get_db` does it once.
  (When the procedure owns the transaction and commits, the later `get_db` commit just commits an empty implicit transaction.)

Consequence worth knowing: in the API flow the COMMIT really happens in `get_db` after the router returned. If that commit fails, the client gets an error and nothing was recorded (atomicity holds).

## 3. Failure handling: XACT_ABORT, XACT_STATE, TRY/CATCH
* `SET XACT_ABORT ON`: any run-time error aborts the batch and rolls the transaction state to "doomed", never leaves half-applied work.
* Inside `CATCH`, `XACT_STATE()` decides: `-1` = doomed, only a FULL `ROLLBACK TRANSACTION` is legal (this also ends a caller's transaction: acceptable for an engine error, the API then returns an error and `get_db` rolls back);
  `1` = still committable => roll back to our savepoint (or fully when we own it); `0` = nothing active (e.g. the engine already rolled back a deadlock victim).
* **Business failures are not raised.** "Not enough stock" etc. are detected with `IF`/`@@ROWCOUNT` and reported via OUTPUT parameters, then the procedure rolls back to its savepoint. A `THROW` would doom the transaction and force the full rollback.
* **Per-item savepoints** (`skip_invalid_items = 1`): `SAVE TRANSACTION sp_item` before each item, `ROLLBACK TRANSACTION sp_item` for a bad one. Rolling back to a savepoint does not release locks acquired before it, and table variables (`@skipped`) are not rolled back.
* Outcome contract (OUTPUT): `@status` = `committed | partial | rolled_back`, `@error_number` (50001..50006 = business, other = engine), `@message`, `@skipped_items` (JSON).

## 4. Python side
* `repository.sales_repository.record_sale` sends ONE batch (`DECLARE ...; EXEC dbo.usp_RecordSale ... ; SELECT <outputs>`), reads the outputs, then reads the sale + items back scoped by `id AND org_id`.
  Business rollback => returns the outcome (the service raises 409/404/422). Engine error => `db.rollback()` and `ProcedureError("... error 1205 ...")`.
* `services.sales_service.create_sale` / `delete_sale` call it through `core.db.run_with_deadlock_retry` (3 retries, backoff 50/100/200 ms, `on_event("deadlock_retry" | "deadlock_gave_up", attempt=..., error=...)`, `on_event` defaults to None).
  A deadlock victim's transaction is already rolled back by SQL Server; the repository also rolls the connection back so the retry starts clean. The unit of work re-runs from the start (read-only pre-checks are repeated).
* Only the repository knows about SQL, procedures or `rollback()`; services see exceptions and outcomes.

## 5. Isolation and concurrency
* Default isolation: READ COMMITTED (locking). The stock decrement is a single statement, so its read and write are one atomic action under the row's exclusive/update lock. See specs/14 (F3) for why that beats "read, check in Python, write".
* N buyers of the last unit: all issue `UPDATE products ... WHERE stock_qty >= @q`; they queue on the row lock; the first commits `stock_qty = 0`; the others re-evaluate the predicate on the committed value, update 0 rows, and report 409. Verified by `tests/sqlserver/test_sales_items_sqlserver.py::test_race_*` (gated).
  Note: in the nested/API flow the lock is held until the request's `commit()`, so the queue is as long as the request, not just the procedure.
* Cash: `UPDATE cash_accounts SET balance = balance + @total` is atomic; it is the LAST write so the contended row lock is short. The lazy first-row creation uses `UPDLOCK, HOLDLOCK` (range lock) to stop two concurrent inserts.
* Void takes `UPDLOCK, HOLDLOCK` on the sale row first, so two concurrent voids serialise and the second reports `not_found`.
* Deadlocks: possible when two transactions lock the same rows in opposite order. Mitigation: items are processed sorted by `product_id`; remaining deadlocks (error 1205, victim chosen by SQL Server) are retried by the service.
* Durability: COMMIT hardens the log. Consistency: CHECK constraints and composite `(id, org_id)` foreign keys hold even for code that bypasses the procedure.

## 6. Rules for later slices
1. A procedure that changes several tables follows the same `@own_tran` / savepoint pattern; do not `BEGIN TRAN ... COMMIT` unconditionally and do not call a bare `ROLLBACK` when nested.
2. Never decide an inventory/balance change from a prior SELECT; put the guard in the `WHERE` of the one statement that changes the row and check `@@ROWCOUNT`.
3. Anything that retries must be a complete unit of work (`run_with_deadlock_retry`); do not retry inside a half-finished transaction.
4. New procedures: org_id in every statement (the static test `test_sale_procedure_sql_scopes_every_tenant_statement_by_org_id` shows how to scan the `.sql` file).

## 7. F4 additions (expenses and amount edits)
* **Same pattern, three more procedures** (`06_expenses_cash.sql`): `@own_tran` first, `BEGIN TRANSACTION` or `SAVE TRANSACTION sp_record_expense | sp_void_expense | sp_adjust_entry`, commit only when owned, savepoint rollback on business failure, `XACT_STATE()` in CATCH.
  Service calls go through `run_with_deadlock_retry`; `repository.base.call_procedure` is the shared EXEC helper (rolls back and raises `ProcedureError` for engine errors, returns business outcomes).
* **A request can run two procedures/statements in ONE transaction**: `PUT /expenses/{id}` with `{amount, description}` runs `usp_AdjustEntryAmount` (nested, savepoint) and then the metadata `UPDATE`; `get_db` commits once at the end, or rolls both back on any exception
  (e.g. the 422 for a sale with items). A deadlock retry re-runs only the procedure call, which is safe because a deadlock victim's work was already undone.
* **Read-modify-write of an amount**: `usp_AdjustEntryAmount` does `SELECT amount ... WITH (UPDLOCK, HOLDLOCK) WHERE id AND org_id`, computes `delta` from that locked value and posts it. Two concurrent edits of the same row queue on that lock, so each delta is
  computed from the previous edit's committed value and `balance == SUM(ledger)` holds (gated test `test_concurrent_adjustments_of_one_expense_serialise`). Contrast with the wrong version "app reads amount, computes delta, calls UPDATE": both would use the same stale old amount.
* **Hot row**: every expense/sale/void/adjustment of an org updates the org's single `cash_accounts` row, as the LAST write of the procedure. In the nested API flow the lock is held until the request's commit, so postings of one org are serialised per request (fine at this scale; concurrent expenses are tested).
* **Lock order** in the procedures: the business row (`expenses`/`sales`, `UPDLOCK`) first, then `cash_accounts`, then `cash_ledger` insert: all five cash-moving procedures take `cash_accounts` last, so they cannot deadlock each other on those two resources.
