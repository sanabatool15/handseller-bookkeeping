"""DB Lab (DEMO ONLY): concurrency demos driven from the UI - a stock race and a deadlock - logged live to txn_log.

Everything here is switched off unless ENABLE_DB_LAB=true (the router answers 404 for every lab route then).

How the demos work (specs/16, specs/15):
  * Every client is a THREAD with its OWN pyodbc connection (`clients.get_db_connection()`), closed in a `finally`, so the
    clients really contend inside SQL Server (they are not serialised by one shared connection).
  * Every client has its own `TxnRecorder` and request id; its events are flushed through the separate autocommit connection
    (`txn_log_service.flush`) when the client finished - the Activity page shows the same txn_started / lock_wait_suspected /
    deadlock_1205_caught / retry_triggered / rolled_back / committed / business_rejected timeline as for normal requests.
  * Each client's unit of work runs through `run_with_deadlock_retry`; the victim of a deadlock is retried.
  * Harmless by construction: the demos only touch `stock_qty` of the caller's own products. The deadlock demo is net zero
    (+1 +1 -1 -1 per client); the race resets the stock to its value from before the run (`restore_stock`, default true).
    No sales or cash entries are created. Do not run the lab while real sales of the same product are in flight.
No SQL here: the SQL statements are in `repository.db_lab_repository`.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Optional

from core import clients
from core.config import get_settings
from core.db import Db, ISOLATION_LEVELS, error_number_of, run_with_deadlock_retry, transaction

from repository import base as repo_base
from repository import db_lab_repository, products_repository
from services import txn_log_service

MODES = ("safe", "unsafe")
MAX_CLIENTS = 10
MAX_QUANTITY = 10
JOIN_TIMEOUT_SECONDS = 120.0


class DisabledError(Exception):
    """ENABLE_DB_LAB is off: the router answers 404 as if the lab did not exist."""


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


def is_enabled() -> bool:
    return bool(get_settings().enable_db_lab)


def status() -> dict[str, bool]:
    return {"enabled": is_enabled()}


def ensure_enabled() -> None:
    if not is_enabled():
        raise DisabledError("DB Lab is disabled")


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid id") from exc


def _delay(value: Any) -> int:
    if isinstance(value, bool) or value not in db_lab_repository.ALLOWED_DELAYS:
        raise ValidationError(f"delay_seconds must be one of {list(db_lab_repository.ALLOWED_DELAYS)}")
    return int(value)


def _isolation(value: Any) -> str:
    if not isinstance(value, str) or value.strip().upper() not in ISOLATION_LEVELS:
        raise ValidationError(f"isolation_level must be one of {list(ISOLATION_LEVELS)}")
    return value.strip().upper()


def _product(db: Db, org_id: str, product_id: str) -> dict[str, Any]:
    """The product, scoped by id AND org_id: another org's product is a 404."""
    product = products_repository.get_product_scoped(db, product_id=product_id, org_id=org_id)
    if product is None:
        raise NotFoundError("Product not found")
    return product


# ----------------------------------------------------------------------------------------------- client threads
def _run_client(
    n: int, *, org_id: str, operation: str, isolation_level: str, deadlock_low: bool,
    work: Callable[[Db], dict[str, Any]], barrier: threading.Barrier, results: list[Optional[dict[str, Any]]],
) -> None:
    """One lab client. Own connection, own recorder; never raises (the outcome goes into `results[n-1]`)."""
    request_id = f"lab-{uuid.uuid4().hex[:16]}"
    result: dict[str, Any] = {"client": n, "request_id": request_id, "status": "rolled_back", "retries": 0, "duration_ms": 0,
                              "error_number": None, "message": None}
    started = time.monotonic()
    db: Optional[Db] = None
    recorder: Optional[txn_log_service.TxnRecorder] = None
    try:
        db = clients.get_db_connection()  # a connection of its own per client, closed in `finally`
        db_lab_repository.prepare_session(db, isolation_level=isolation_level, deadlock_low=deadlock_low)
        recorder = txn_log_service.recorder_for(request_id, org_id, db)
        try:
            barrier.wait(timeout=30)  # all clients start together
        except threading.BrokenBarrierError:
            raise RuntimeError("DB Lab start aborted: another client failed to connect")

        def attempt() -> dict[str, Any]:
            with transaction(db):  # commit on success, rollback + re-raise on error: a retry starts clean
                return work(db)

        outcome = run_with_deadlock_retry(attempt, on_event=recorder.on_event, operation=operation)
        if outcome["status"] == "committed":
            recorder.committed()
            result.update(status="committed", message="committed")
        else:
            txn_log_service.report_rejected(recorder.on_event, operation=operation, error_number=outcome.get("error_number"), message=outcome.get("message"))
            result.update(status="rejected", error_number=outcome.get("error_number"), message=outcome.get("message"))
    except BaseException as exc:  # noqa: BLE001 - a client failure is a result, not a crash of the demo
        barrier.abort()
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        if recorder is not None:
            recorder.rolled_back(exc)
        result.update(status="rolled_back", error_number=error_number_of(exc), message=str(exc)[:300])
    finally:
        if recorder is not None:
            result["retries"] = recorder.retries
            # A client that survived a deadlock reports the engine error it saw, even when the retry committed.
            for e in recorder.events:
                if e["step"] in ("deadlock_1205_caught", "lock_timeout_caught"):
                    result["error_number"] = e["error_number"]
                    break
        if db is not None:
            try:
                db_lab_repository.reset_session(db)
            except Exception:  # noqa: BLE001
                pass
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        if recorder is not None:
            txn_log_service.flush(recorder)
        results[n - 1] = result


def _run_clients(specs: list[dict[str, Any]], *, org_id: str) -> list[dict[str, Any]]:
    barrier = threading.Barrier(len(specs))
    results: list[Optional[dict[str, Any]]] = [None] * len(specs)
    threads = [
        threading.Thread(target=_run_client, name=f"db-lab-client-{i + 1}", daemon=True, args=(i + 1,),
                         kwargs={"org_id": org_id, "barrier": barrier, "results": results, **spec})
        for i, spec in enumerate(specs)
    ]
    for t in threads:
        t.start()
    deadline = time.monotonic() + JOIN_TIMEOUT_SECONDS
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.monotonic()))
    return [
        r if r is not None else {"client": i + 1, "request_id": None, "status": "rolled_back", "retries": 0, "duration_ms": 0,
                                 "error_number": None, "message": "client did not finish in time"}
        for i, r in enumerate(results)
    ]


def _count(results: list[dict[str, Any]], status: str) -> int:
    return sum(1 for r in results if r["status"] == status)


# ----------------------------------------------------------------------------------------------- the demos
def race_sale(
    db: Db, *, org_id: str, product_id: str, quantity: int = 1, clients_n: int = 2, mode: str = "safe",
    isolation_level: str = "READ COMMITTED", delay_seconds: int = 1, restore_stock: bool = True,
) -> dict[str, Any]:
    """N clients sell `quantity` of one product at the same moment. mode 'safe' = guarded single-statement decrement (one
    winner for the last unit); 'unsafe' = naive read-then-write (can oversell at READ COMMITTED)."""
    ensure_enabled()
    product_id = _uuid(product_id, "product_id")
    if mode not in MODES:
        raise ValidationError(f"mode must be one of {list(MODES)}")
    if isinstance(clients_n, bool) or not isinstance(clients_n, int) or not 2 <= clients_n <= MAX_CLIENTS:
        raise ValidationError(f"clients must be a whole number between 2 and {MAX_CLIENTS}")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        raise ValidationError(f"quantity must be a whole number between 1 and {MAX_QUANTITY}")
    isolation_level, delay_seconds = _isolation(isolation_level), _delay(delay_seconds)
    before = int(_product(db, org_id, product_id)["stock_qty"])

    sale = db_lab_repository.safe_sale if mode == "safe" else db_lab_repository.naive_sale
    spec = {
        "operation": f"lab_race_sale_{mode}", "isolation_level": isolation_level, "deadlock_low": False,
        "work": lambda conn: sale(conn, org_id=org_id, product_id=product_id, quantity=quantity, delay_seconds=delay_seconds),
    }
    results = _run_clients([spec] * clients_n, org_id=org_id)

    after_race = _stock(db, org_id, product_id)
    restored = False
    if restore_stock and after_race != before:
        with transaction(db):
            db_lab_repository.reset_stock(db, org_id=org_id, product_id=product_id, qty=before)
        restored = True
    final = _stock(db, org_id, product_id)
    committed = _count(results, "committed")
    oversold = max(0, committed * quantity - before)
    return {
        "demo_only": True, "kind": "race_sale", "mode": mode, "isolation_level": isolation_level, "product_id": product_id,
        "quantity": quantity, "clients": clients_n, "delay_seconds": delay_seconds,
        "stock_before": before, "stock_after_race": after_race, "stock_after": final, "restored": restored,
        "results": results,
        "summary": {
            "committed": committed, "rejected": _count(results, "rejected"), "rolled_back": _count(results, "rolled_back"),
            "deadlock_victims": sum(1 for r in results if r["error_number"] == 1205), "oversold_units": oversold,
        },
        "verdict": (
            f"OVERSOLD: {committed} clients sold {quantity} unit(s) each but only {before} unit(s) existed (lost update)." if oversold
            else "No oversell: no more units were sold than existed."
        ),
    }


def _stock(db: Db, org_id: str, product_id: str) -> int:
    return int(_product(db, org_id, product_id)["stock_qty"])


def deadlock(
    db: Db, *, org_id: str, product_a: str, product_b: str, delay_seconds: int = 1, fixed: bool = False,
) -> dict[str, Any]:
    """Two clients lock two products. fixed=False: opposite order (A,B) and (B,A) => SQL Server raises 1205 for one victim,
    which is retried. fixed=True: both lock in ascending id order => no deadlock (deadlock PREVENTION by lock ordering)."""
    ensure_enabled()
    a, b = _uuid(product_a, "product_a"), _uuid(product_b, "product_b")
    if a == b:
        raise ValidationError("product_a and product_b must be two different products")
    delay_seconds = _delay(delay_seconds)
    before = {a: _stock(db, org_id, a), b: _stock(db, org_id, b)}

    def spec(first: str, second: str, low: bool) -> dict[str, Any]:
        return {
            "operation": "lab_deadlock_fixed" if fixed else "lab_deadlock", "isolation_level": "READ COMMITTED",
            "deadlock_low": low,
            "work": lambda conn: db_lab_repository.lock_pair(conn, org_id=org_id, first=first, second=second, delay_seconds=delay_seconds),
        }

    if fixed:
        lo, hi = sorted((a, b))
        specs = [spec(lo, hi, False), spec(lo, hi, False)]  # same order for everybody
    else:
        specs = [spec(a, b, False), spec(b, a, True)]  # opposite order; client 2 is the preferred victim
    results = _run_clients(specs, org_id=org_id)
    after = {a: _stock(db, org_id, a), b: _stock(db, org_id, b)}
    victims = sum(1 for r in results if r["error_number"] == 1205)
    return {
        "demo_only": True, "kind": "deadlock_fixed" if fixed else "deadlock", "delay_seconds": delay_seconds,
        "product_a": a, "product_b": b, "stock_before": before, "stock_after": after, "restored": before == after,
        "results": results,
        "summary": {"committed": _count(results, "committed"), "rejected": _count(results, "rejected"),
                    "rolled_back": _count(results, "rolled_back"), "deadlock_victims": victims,
                    "retries": sum(r["retries"] for r in results)},
        "verdict": (
            "Deadlock prevented: both clients locked the products in the same order, so one simply waited for the other." if fixed and victims == 0
            else f"Deadlock: SQL Server chose {victims} victim(s) (error 1205); the victim was retried." if victims
            else "No deadlock happened this time (the clients did not overlap)."
        ),
    }
