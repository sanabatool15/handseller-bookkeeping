# Transactions and concurrency (slice F3 onward; F5 adds the transaction log and the DB Lab, sections 8-12)

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

## 8. F5: the transaction event log (`txn_log`) - what is logged and why it lives OUTSIDE the transaction

**Purpose.** The course demo must SHOW real transactions, lock contention, deadlocks (error 1205), retries, rollbacks and commits, live, from the app.
`sql_server/07_txn_log.sql` adds `txn_log`; the Activity page (`/activity`, specs/16) reads it through `GET /db-logs` and `GET /db-logs/requests`.

### Event model (one row per event; `repository/txn_log_repository.py`, `services/txn_log_service.py::TxnRecorder`)
| step | when | extra |
|---|---|---|
| `txn_started` | before every attempt of a unit of work (`retry_no` = attempt - 1) | |
| `lock_wait_suspected` | an attempt took >= `LOCK_WAIT_SUSPECT_MS` (default 300 ms) | `duration_ms`; **inferred**, see below |
| `deadlock_1205_caught` | SQL Server chose this attempt as a deadlock victim (it already rolled the attempt back) | `error_number` 1205, `duration_ms` of the attempt |
| `lock_timeout_caught` | lock wait timed out (error 1222) | |
| `retry_triggered` | `run_with_deadlock_retry` is about to re-run the whole unit of work | `retry_no` = n (1..3) |
| `business_rejected` | a business rule refused the request (insufficient stock 50001, product/customer/sale/expense not found, not allowed, validation 50003). The procedure rolled back to ITS savepoint; this is **not** an engine rollback | `error_number` = the procedure's number |
| `rolled_back` | the request transaction was rolled back: engine error, retries exhausted, any failure after work was done | `error_number` when known, `message` = the reason |
| `committed` | the request transaction really committed (`db.commit()` succeeded) | `duration_ms` = whole request, `retry_no` = retries used |

`status` is a step-level label (`started`, `suspected`, `error`, `retrying`, `rejected`, `rolled_back`, `committed`); `isolation_level` is the effective level of the business connection.
`GET /db-logs/requests` groups by `request_id` in SQL (`GROUP BY`) and derives the final `outcome`: `committed`, `deadlock_retried` (committed after >= 1 retry), `rolled_back`, `rejected` (business rule), `in_progress`.

Which requests are instrumented: the five money paths, i.e. `record_sale`, `void_sale`, `record_expense`, `void_expense`, `adjust_entry_amount` (the amount part of `PUT /sales|expenses/{id}`), plus the DB Lab clients.
Reads and uninstrumented writes leave no log (the recorder has no events, so nothing is written). A replayed `Idempotency-Key` returns the cached response without running anything and therefore logs nothing; it still gets its own `X-Request-ID`.

### How events are produced
`core.db.run_with_deadlock_retry(fn, on_event=..., operation=...)` now tells the hook about every `txn_started`, `attempt_ok`, `attempt_failed`, `deadlock_retry`, `deadlock_gave_up` (with `operation`, `attempt`, `elapsed_ms`, `error`, `error_number`);
the old step names/`attempt`/`error` keys are unchanged. The services pass `on_event=recorder.on_event` + their operation name and call `txn_log_service.report_rejected(...)` for business refusals.
A failing hook can never change the result of the unit of work (exceptions in the hook are swallowed).

### Why the log is written OUTSIDE the business transaction
If the rows were inserted on the request's own connection they would be part of the transaction that the failure rolls back: the very requests worth looking at (rolled back, deadlocked) would leave no trace.
So: the recorder keeps the events **in memory** during the request; `routers/deps.py::get_db`, after `db.commit()` / `db.rollback()` has really run (and after the connection was closed), calls `txn_log_service.flush()`,
which opens a SEPARATE connection with **autocommit ON** (`core.clients.get_autocommit_connection()`) and inserts the whole batch in ONE statement. Each statement on that connection commits by itself, independent of the business transaction.
Flush failures are logged and swallowed (a broken log must never turn a successful request into an error).

**Dependency order vs middleware (decision).** The flush lives in the teardown of the `get_db` dependency, not in a middleware, because (1) it runs exactly when the business transaction has finished, in the same function that does the commit/rollback, so
the order cannot be wrong; (2) the recorder needs `request.state.user.org_id` and the `db` handle, both available there; (3) a middleware sees only the response, not whether the commit succeeded. A middleware does one job: `RequestIdMiddleware` (id + header).
**FastAPI scope trap found while building this:** with FastAPI >= 0.118 the exit code of a `yield` dependency runs AFTER the response was sent by default. That means the old `Depends(get_db)` committed after the 201 was already on the wire (a client could read before the commit; a failing commit
could no longer change the response), and the log flush would run even later. All routers therefore use `DB = Depends(get_db, scope="function")` (`routers/deps.py`): commit/rollback and flush now run right after the route function returns, BEFORE the response is sent.
`tests/integration/test_txn_log_api.py` guards this (static scan of the routers + "the log row exists when the client has the response").

**Side effect worth knowing.** The recorder reads the isolation level (`SELECT ... FROM sys.dm_exec_sessions WHERE session_id = @@SPID`) on the business connection when the first attempt starts. Under implicit transactions that SELECT opens the request transaction, so
the stored procedures called afterwards always run NESTED (`@own_tran = 0`, savepoint, no commit): the commit is always `get_db`'s. Before F5 a procedure could be the owner and commit by itself when nothing had been read first (e.g. `DELETE /sales/{id}`), after which a later failure could not undo it.

### `lock_wait_suspected` is INFERRED
The application cannot observe lock waits: pyodbc does not report them and the lock manager is not queried. The recorder only measures how long an attempt took; if it reached `LOCK_WAIT_SUSPECT_MS` it records "a lock wait is SUSPECTED". A slow disk, a cold plan or network latency look identical.
The UI and docs must never state more than that. (Real waits can be seen in SSMS with `sys.dm_tran_locks` / `sys.dm_os_waiting_tasks` while a demo runs; see TEST_CASES F5-06.)

### Isolation level
`Db.get_isolation_level()` reports the effective level of a session (`sys.dm_exec_sessions.transaction_isolation_level`; READ COMMITTED is reported even when the database uses `READ_COMMITTED_SNAPSHOT`) and is stored on every event.
`Db.set_isolation_level(level)` accepts only {READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE, SNAPSHOT}: the statement text is **looked up** in a dict, never formatted; anything else raises `ValueError` before any SQL. Only the DB Lab changes the level (on its own connections); normal requests always run at the default.
SNAPSHOT additionally needs `ALTER DATABASE HandsellerDB SET ALLOW_SNAPSHOT_ISOLATION ON` (not done by the scripts, see the header of 07), otherwise SQL Server answers error 3952.

### Request ids
`RequestIdMiddleware` gives each request an id and returns it as `X-Request-ID` on every response (also 401/400; 500s get it from the exception handler). An incoming `X-Request-ID` is honoured ONLY if it matches `^[A-Za-z0-9._-]{8,64}$`; otherwise a fresh uuid4 hex is used (so a client cannot inject odd text into the log or the UI).
The id is in the 409 body as `request_id` (so the Activity page can be opened for a refused sale); other bodies are unchanged on purpose (the 404 bodies of a foreign and an unknown id must stay identical; the 201 sale shape is the UI's contract). CORS exposes the header.

## 9. F5: DB Lab (demo only, `ENABLE_DB_LAB=true`)
Concurrency demos driven from the UI; every route except `GET /db-lab/status` answers 404 while the setting is off (the default). Code: `routers/db_lab_router.py`, `services/db_lab_service.py`, `repository/db_lab_repository.py`. Details and page behaviour: specs/16.

* **Threads, each with its own connection.** `race-sale`, `deadlock` and `deadlock-fixed` start N threads; every thread opens its own pyodbc connection (`core.clients.get_db_connection()`), closes it in a `finally`, has its own `TxnRecorder` and request id, and flushes its events through the autocommit log connection. A thread barrier makes them start together.
  (This is why `services/db_lab_service.py` and `services/txn_log_service.py` import `core.clients`: the same documented exception as `health_service`; they still never run SQL.)
* **`unsafe` race** = the textbook lost update: `SELECT stock_qty` ; `WAITFOR DELAY` (1 s default) ; `UPDATE products SET stock_qty = <read - qty>`.
  READ COMMITTED: the read holds no lock, N clients read the same value and all "sell" the last unit => oversell (`committed` > stock). REPEATABLE READ / SERIALIZABLE: the read keeps a shared lock until commit, so the writes
  need a lock the other readers hold: **conversion deadlock**, one victim (1205) is retried and then reads the real value => no oversell. SNAPSHOT: the second writer fails with 3960 (update conflict) and rolls back.
* **`safe` race** = the same single guarded statement the real stock path uses (`UPDATE ... WHERE stock_qty >= @q`, specs/14), followed by the chosen delay while the lock is held, so the other clients visibly queue (`lock_wait_suspected`) and then touch 0 rows (`business_rejected`).
  It deliberately does NOT create sale/cash rows: the demo must leave no bookkeeping residue.
* **`deadlock`**: client 1 locks product A then B, client 2 locks B then A, with the delay between the two locks. SQL Server's deadlock monitor (wakes about every 5 s, faster once deadlocks occur) picks a victim; client 2 runs with `SET DEADLOCK_PRIORITY LOW` so it is the (deterministic) victim.
  The victim gets 1205 -> `deadlock_1205_caught`, `retry_triggered(1)`, a new transaction, `committed`. **`deadlock-fixed`**: both clients lock in ascending id order (the standard prevention) => nobody is a victim.
* **Harmless by construction.** Lab connections use `SET LOCK_TIMEOUT 15000` (a lab never hangs for ever) and are reset (isolation READ COMMITTED, no timeout, normal priority) before they go back to the pool. The deadlock demo changes stock by +1 +1 -1 -1 per client (net zero, rolled back on any error).
  The race resets the product to its stock from BEFORE the run when it finishes (`restore_stock`, default true; the response shows before / after the race / after). Only the caller's own products are touched; every statement carries `org_id`. Do not run it while the same product is really being sold.
