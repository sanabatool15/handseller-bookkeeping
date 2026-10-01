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
CONSTRAINT_CONFLICT_ERROR = 547  # shared by CHECK and FOREIGN KEY/REFERENCE conflicts: the message text tells them apart


# Isolation levels an application caller may ask for. The statement text is looked up in this dict, so user
# input is NEVER interpolated into SQL: an unknown level raises ValueError before any SQL is built.
ISOLATION_STATEMENTS = {
    "READ UNCOMMITTED": "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
    "READ COMMITTED": "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
    "REPEATABLE READ": "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
    "SERIALIZABLE": "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
    "SNAPSHOT": "SET TRANSACTION ISOLATION LEVEL SNAPSHOT",
}
ISOLATION_LEVELS = tuple(ISOLATION_STATEMENTS)
# sys.dm_exec_sessions.transaction_isolation_level: 0 = unspecified (reported as the default, READ COMMITTED)
_ISOLATION_BY_CODE = {0: "READ COMMITTED", 1: "READ UNCOMMITTED", 2: "READ COMMITTED", 3: "REPEATABLE READ",
                      4: "SERIALIZABLE", 5: "SNAPSHOT"}


class UniqueViolationError(Exception):
    """A UNIQUE constraint/index rejected the statement (SQL Server 2627/2601)."""


class ForeignKeyViolationError(Exception):
    """A FOREIGN KEY / REFERENCE constraint rejected the statement (SQL Server 547), e.g. deleting a row that
    other rows still point at. CHECK-constraint 547s are NOT mapped (they stay plain driver errors)."""


def _error_text(exc: BaseException) -> str:
    return " ".join(str(a) for a in getattr(exc, "args", ())) or str(exc)


def _has_code(exc: BaseException, codes: Sequence[int]) -> bool:
    text = _error_text(exc)
    return any(re.search(rf"\b{c}\b", text) for c in codes)


def is_deadlock(exc: BaseException, *, include_lock_timeout: bool = True) -> bool:
    codes = [DEADLOCK_ERROR] + ([LOCK_TIMEOUT_ERROR] if include_lock_timeout else [])
    return _has_code(exc, codes) or "40001" in _error_text(exc)


def error_number_of(exc: BaseException) -> Optional[int]:
    """Best-effort SQL Server error number of a driver/procedure error (None when unknown).

    A `ProcedureError` carries it as `.error_number`; a pyodbc error has it in the message text, e.g.
    "... was deadlocked ... (1205) (SQLExecDirectW)"; SQLSTATE 40001 is the deadlock victim state."""
    number = getattr(exc, "error_number", None)
    if isinstance(number, int):
        return number
    text = _error_text(exc)
    if _has_code(exc, [DEADLOCK_ERROR]) or "40001" in text:
        return DEADLOCK_ERROR
    if _has_code(exc, [LOCK_TIMEOUT_ERROR]):
        return LOCK_TIMEOUT_ERROR
    found = re.search(r"\((\d{3,5})\)", text)
    return int(found.group(1)) if found else None


def is_unique_violation(exc: BaseException) -> bool:
    return _has_code(exc, UNIQUE_VIOLATION_ERRORS)


def is_foreign_key_violation(exc: BaseException) -> bool:
    text = _error_text(exc)
    return _has_code(exc, (CONSTRAINT_CONFLICT_ERROR,)) and bool(
        re.search(r"REFERENCE constraint|FOREIGN KEY constraint", text, re.I)
    )


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
            if is_foreign_key_violation(exc):
                raise ForeignKeyViolationError(_error_text(exc)) from exc
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

    def get_isolation_level(self) -> str:
        """Effective isolation level of THIS session (from sys.dm_exec_sessions; a session can always see itself).
        Note: READ COMMITTED is reported even when the database uses READ_COMMITTED_SNAPSHOT."""
        row = self.query_one("SELECT transaction_isolation_level AS level FROM sys.dm_exec_sessions WHERE session_id = @@SPID")
        return _ISOLATION_BY_CODE.get(int(row["level"]) if row else 0, "READ COMMITTED")

    def set_isolation_level(self, level: str) -> None:
        """SET TRANSACTION ISOLATION LEVEL for this session. `level` must be in ISOLATION_LEVELS (allow-list);
        anything else raises ValueError and nothing is sent to the server."""
        statement = ISOLATION_STATEMENTS.get(str(level).strip().upper()) if isinstance(level, str) else None
        if statement is None:
            raise ValueError(f"isolation level must be one of {list(ISOLATION_LEVELS)}")
        self.execute(statement)

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
    operation: Optional[str] = None,
) -> T:
    """Call `fn()`; if it fails with a deadlock, retry up to `retries` more times.

    `fn` must be a complete unit of work (it should open/own its transaction) so
    a retry starts from a clean state. `on_event(step, **info)` is told, with `operation` and `attempt` (1-based)
    in `info` every time:
      "txn_started"     before each attempt;
      "attempt_ok"      `fn` returned (elapsed_ms) - note a returned business outcome is still "ok" here;
      "attempt_failed"  `fn` raised something that is not a deadlock (error, error_number, elapsed_ms); re-raised;
      "deadlock_retry"  victim of 1205 / lock timeout 1222 and another attempt follows (error, error_number, elapsed_ms);
      "deadlock_gave_up" same, but retries are exhausted; re-raised.
    A failing hook never breaks the unit of work.
    """
    attempt = 0

    def emit(step: str, **info: Any) -> None:
        if on_event is None:
            return
        try:
            on_event(step, operation=operation, **info)
        except Exception:  # noqa: BLE001 - observability must never change the outcome
            pass

    while True:
        attempt += 1
        emit("txn_started", attempt=attempt)
        started = time.monotonic()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if not is_deadlock(exc, include_lock_timeout=include_lock_timeout):
                emit("attempt_failed", attempt=attempt, elapsed_ms=elapsed_ms, error=_error_text(exc), error_number=error_number_of(exc))
                raise
            if attempt > retries:
                emit("deadlock_gave_up", attempt=attempt, elapsed_ms=elapsed_ms, error=_error_text(exc), error_number=error_number_of(exc))
                raise
            emit("deadlock_retry", attempt=attempt, elapsed_ms=elapsed_ms, error=_error_text(exc), error_number=error_number_of(exc))
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
            continue
        emit("attempt_ok", attempt=attempt, elapsed_ms=int((time.monotonic() - started) * 1000))
        return result


def _datetimeoffset_converter(raw: bytes) -> str:
    # ODBC SQL_SS_TIMESTAMPOFFSET_STRUCT: year, month, day, hour, minute, second (shorts),
    # fraction in nanoseconds (uint), tz hour offset, tz minute offset (shorts)
    y, mo, d, h, mi, s, ns, tzh, tzm = struct.unpack("<6hI2h", raw)
    tz = _dt.timezone(_dt.timedelta(hours=tzh, minutes=tzm))
    return _dt.datetime(y, mo, d, h, mi, s, ns // 1000, tzinfo=tz).isoformat()


def connect(connection_string: str, *, autocommit: bool = False) -> Db:
    """Open a real pyodbc connection (autocommit off unless asked). Imports pyodbc lazily."""
    import pyodbc  # noqa: PLC0415

    conn = pyodbc.connect(connection_string, autocommit=autocommit)
    conn.add_output_converter(-155, _datetimeoffset_converter)  # datetimeoffset
    return Db(conn)
