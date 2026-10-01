"""SQL Server access primitives (pyodbc).

Only `repository/*.py` may call `Db.query/query_one/execute`; services and
routers must never write SQL (see specs/01 and specs/13).

* `Db` wraps ONE pyodbc connection with autocommit OFF.
* `transaction(db)` commits on success and rolls back on any exception.
* `run_with_deadlock_retry(fn)` re-runs a unit of work when SQL Server picks it
  as a deadlock victim (error 1205) or a lock wait times out (1222).
* Rows come back as plain dicts with JSON-friendly values so response shapes are
  identical to the old Supabase ones: uniqueidentifier -> str, Decimal -> float,
  date/datetime -> ISO string.

pyodbc is imported lazily so unit tests run without an ODBC driver installed.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import re
import struct
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, Sequence, TypeVar

T = TypeVar("T")

DEADLOCK_ERROR = 1205
LOCK_TIMEOUT_ERROR = 1222
UNIQUE_VIOLATION_ERRORS = (2627, 2601)


class UniqueViolationError(Exception):
    """A UNIQUE constraint/index rejected the statement (SQL Server 2627/2601)."""


def _error_text(exc: BaseException) -> str:
    return " ".join(str(a) for a in getattr(exc, "args", ())) or str(exc)


def _has_code(exc: BaseException, codes: Sequence[int]) -> bool:
    text = _error_text(exc)
    return any(re.search(rf"\b{c}\b", text) for c in codes)


def is_deadlock(exc: BaseException, *, include_lock_timeout: bool = True) -> bool:
    codes = [DEADLOCK_ERROR] + ([LOCK_TIMEOUT_ERROR] if include_lock_timeout else [])
    return _has_code(exc, codes) or "40001" in _error_text(exc)


def is_unique_violation(exc: BaseException) -> bool:
    return _has_code(exc, UNIQUE_VIOLATION_ERRORS)


def normalise_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def normalise_row(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {c: normalise_value(v) for c, v in zip(columns, row)}


class Db:
    """Thin wrapper over one DB-API connection (autocommit off)."""

    def __init__(self, conn: Any):
        self._conn = conn

    def _run(self, sql: str, params: Sequence[Any]):
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, tuple(params))
        except Exception as exc:  # noqa: BLE001
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
            if is_unique_violation(exc):
                raise UniqueViolationError(_error_text(exc)) from exc
            raise
        return cursor

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self._run(sql, params)
        try:
            if cursor.description is None:
                return []
            columns = [d[0] for d in cursor.description]
            return [normalise_row(columns, r) for r in cursor.fetchall()]
        finally:
            cursor.close()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        cursor = self._run(sql, params)
        try:
            return cursor.rowcount
        finally:
            cursor.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


@contextmanager
def transaction(db: Db) -> Iterator[Db]:
    """Commit if the block succeeds, roll back (and re-raise) if it raises."""
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


def run_with_deadlock_retry(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    on_event: Optional[Callable[..., None]] = None,
    backoff_seconds: float = 0.05,
    include_lock_timeout: bool = True,
) -> T:
    """Call `fn()`; if it fails with a deadlock, retry up to `retries` more times.

    `fn` must be a complete unit of work (it should open/own its transaction) so
    a retry starts from a clean state. `on_event(step, **info)` is told about
    "deadlock_retry" and "deadlock_gave_up".
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not is_deadlock(exc, include_lock_timeout=include_lock_timeout):
                raise
            if attempt >= retries:
                if on_event:
                    on_event("deadlock_gave_up", attempt=attempt + 1, error=_error_text(exc))
                raise
            attempt += 1
            if on_event:
                on_event("deadlock_retry", attempt=attempt, error=_error_text(exc))
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))


def _datetimeoffset_converter(raw: bytes) -> str:
    # ODBC SQL_SS_TIMESTAMPOFFSET_STRUCT: year, month, day, hour, minute, second (shorts),
    # fraction in nanoseconds (uint), tz hour offset, tz minute offset (shorts)
    y, mo, d, h, mi, s, ns, tzh, tzm = struct.unpack("<6hI2h", raw)
    tz = _dt.timezone(_dt.timedelta(hours=tzh, minutes=tzm))
    return _dt.datetime(y, mo, d, h, mi, s, ns // 1000, tzinfo=tz).isoformat()


def connect(connection_string: str) -> Db:
    """Open a real pyodbc connection (autocommit off). Imports pyodbc lazily."""
    import pyodbc  # noqa: PLC0415

    conn = pyodbc.connect(connection_string, autocommit=False)
    conn.add_output_converter(-155, _datetimeoffset_converter)  # datetimeoffset
    return Db(conn)
