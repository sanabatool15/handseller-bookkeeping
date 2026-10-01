"""DB Lab repository (DEMO ONLY, gated by ENABLE_DB_LAB; see specs/16). All SQL of the concurrency demos lives here.

Every statement is static, uses `?` placeholders and carries org_id. The only things that are not parameters:
  * WAITFOR DELAY: a fixed literal per allowed number of seconds (`_WAIT`); the delay is looked up in that dict
    (allow-list 1..5, 0 = no wait), never formatted into SQL.
  * `SET LOCK_TIMEOUT 15000` / `SET DEADLOCK_PRIORITY ...` / isolation levels: fixed literals as well (isolation levels via
    the allow-list in core.db.Db.set_isolation_level).
The lab only ever changes products.stock_qty of the caller's own products, and every demo is net-zero or reset afterwards
by the service (see db_lab_service).
"""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db

ALLOWED_DELAYS = (0, 1, 2, 3, 4, 5)
_WAIT = {
    1: "WAITFOR DELAY '00:00:01'",
    2: "WAITFOR DELAY '00:00:02'",
    3: "WAITFOR DELAY '00:00:03'",
    4: "WAITFOR DELAY '00:00:04'",
    5: "WAITFOR DELAY '00:00:05'",
}
# A lab connection never blocks forever: after 15 s a lock wait fails with error 1222 (the retry wrapper handles it).
_LOCK_TIMEOUT_ON = "SET LOCK_TIMEOUT 15000"
_LOCK_TIMEOUT_OFF = "SET LOCK_TIMEOUT -1"
_PRIORITY_LOW = "SET DEADLOCK_PRIORITY LOW"
_PRIORITY_NORMAL = "SET DEADLOCK_PRIORITY NORMAL"

_READ_STOCK = "SELECT stock_qty FROM products WHERE id = ? AND org_id = ?"
# NAIVE write of a value computed by the application from an earlier read: this is the lost-update bug on purpose.
_WRITE_STOCK = "UPDATE products SET stock_qty = ? WHERE id = ? AND org_id = ?"
# The race-safe decrement (same guarded single statement as the real stock path): zero rows = refused.
_SAFE_DECREMENT = "UPDATE products SET stock_qty = stock_qty - ? WHERE id = ? AND org_id = ? AND stock_qty >= ?"
# +delta/-delta that nets to zero inside one transaction; takes the row's exclusive lock.
_TOUCH = "UPDATE products SET stock_qty = stock_qty + ? WHERE id = ? AND org_id = ?"


def prepare_session(db: Db, *, isolation_level: str, deadlock_low: bool = False) -> None:
    """Session settings of a lab connection (isolation level from the allow-list, lock timeout, deadlock priority)."""
    db.set_isolation_level(isolation_level)
    db.execute(_LOCK_TIMEOUT_ON)
    if deadlock_low:
        db.execute(_PRIORITY_LOW)


def reset_session(db: Db) -> None:
    """Undo prepare_session before the (pooled) connection goes back."""
    db.set_isolation_level("READ COMMITTED")
    db.execute(_LOCK_TIMEOUT_OFF)
    db.execute(_PRIORITY_NORMAL)


def wait(db: Db, seconds: int) -> None:
    """WAITFOR DELAY for an allow-listed number of seconds (0 = no wait)."""
    if seconds == 0:
        return
    statement = _WAIT.get(seconds) if isinstance(seconds, int) and not isinstance(seconds, bool) else None
    if statement is None:
        raise ValueError(f"delay must be one of {list(ALLOWED_DELAYS)} seconds")
    db.execute(statement)


def safe_decrement(db: Db, *, org_id: str, product_id: str, quantity: int) -> bool:
    """The guarded single-statement decrement; False = 0 rows touched (not enough stock or no such product)."""
    return db.execute(_SAFE_DECREMENT, (int(quantity), product_id, org_id, int(quantity))) > 0


def read_stock(db: Db, *, org_id: str, product_id: str) -> Optional[int]:
    row = db.query_one(_READ_STOCK, (product_id, org_id))
    return None if row is None else int(row["stock_qty"])


def write_stock(db: Db, *, org_id: str, product_id: str, new_qty: int) -> bool:
    return db.execute(_WRITE_STOCK, (int(new_qty), product_id, org_id)) > 0


def touch_stock(db: Db, *, org_id: str, product_id: str, delta: int) -> bool:
    return db.execute(_TOUCH, (int(delta), product_id, org_id)) > 0


def naive_sale(db: Db, *, org_id: str, product_id: str, quantity: int, delay_seconds: int) -> dict[str, Any]:
    """UNSAFE read-then-write: SELECT stock; WAITFOR; UPDATE stock = read - quantity. The caller's transaction decides
    visibility: at READ COMMITTED the read holds no lock, so concurrent clients all read the same value and overwrite each
    other (lost update / oversell). At REPEATABLE READ / SERIALIZABLE the read keeps a shared lock until commit, so the
    writes queue or deadlock (1205); at SNAPSHOT the second writer fails with 3960 (update conflict)."""
    stock = read_stock(db, org_id=org_id, product_id=product_id)
    if stock is None:
        return {"status": "rejected", "error_number": 50002, "message": "Product not found"}
    if stock < quantity:
        return {"status": "rejected", "error_number": 50001, "message": f"Not enough stock (saw {stock}, wanted {quantity})", "stock_read": stock}
    wait(db, delay_seconds)
    write_stock(db, org_id=org_id, product_id=product_id, new_qty=stock - quantity)
    return {"status": "committed", "stock_read": stock}


def safe_sale(db: Db, *, org_id: str, product_id: str, quantity: int, delay_seconds: int) -> dict[str, Any]:
    """SAFE: one guarded UPDATE (`WHERE ... AND stock_qty >= ?`) takes the row's exclusive lock and decides in the same
    statement; the delay then simulates a slow commit so the other clients visibly queue behind the lock. Losers re-evaluate
    the guard on the committed value and touch 0 rows."""
    if not safe_decrement(db, org_id=org_id, product_id=product_id, quantity=quantity):
        return {"status": "rejected", "error_number": 50001, "message": "Not enough stock (guarded UPDATE touched 0 rows)"}
    wait(db, delay_seconds)
    return {"status": "committed"}


def lock_pair(db: Db, *, org_id: str, first: str, second: str, delay_seconds: int) -> dict[str, Any]:
    """Lock `first`, wait, lock `second` (each +1), then give both back (-1, -1): net zero when it commits. Two clients that
    call this with the two ids in OPPOSITE order deadlock; with the SAME order they just queue."""
    # A missing product raises (instead of returning) so the caller's transaction ROLLS BACK the earlier +1: net zero always.
    if not touch_stock(db, org_id=org_id, product_id=first, delta=1):
        raise LookupError("Product not found")
    wait(db, delay_seconds)
    if not touch_stock(db, org_id=org_id, product_id=second, delta=1):
        raise LookupError("Product not found")
    touch_stock(db, org_id=org_id, product_id=first, delta=-1)
    touch_stock(db, org_id=org_id, product_id=second, delta=-1)
    return {"status": "committed"}


def reset_stock(db: Db, *, org_id: str, product_id: str, qty: int) -> bool:
    """Put the demo product back to its stock from before the lab ran."""
    return write_stock(db, org_id=org_id, product_id=product_id, new_qty=qty)
