"""Transaction event log: the in-memory `TxnRecorder`, flush to the database, and the read side (Activity page).

How a request gets logged (full story in specs/15):
  1. `routers.deps.get_db` creates a `TxnRecorder` for the request (request id from the RequestId middleware).
  2. A service wraps its repository call in `run_with_deadlock_retry(..., on_event=recorder.on_event, operation=...)`;
     the hook tells the recorder about every attempt, deadlock and retry, and the service reports business refusals.
  3. When the business transaction has really committed / rolled back, `get_db` tells the recorder (`committed()` /
     `rolled_back()`) and then calls `flush()`, which writes all events through a SEPARATE AUTOCOMMIT connection.
     That is why a rolled-back request still leaves its log.
No SQL here: persistence is `repository.txn_log_repository`.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from typing import Any, Callable, Optional

from core import clients
from core.config import get_settings
from core.db import error_number_of, is_deadlock

from repository import txn_log_repository

logger = logging.getLogger("handseller.txn_log")

STEPS = txn_log_repository.STEPS
OUTCOMES = ("committed", "deadlock_retried", "rolled_back", "rejected", "in_progress")
MAX_MESSAGE = 400
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")  # what an incoming X-Request-ID may look like
MAX_LIMIT = 200


class ValidationError(Exception):
    pass


def is_safe_request_id(value: Optional[str]) -> bool:
    return bool(value) and _REQUEST_ID_RE.match(value) is not None


def _utcnow() -> dt.datetime:
    """Naive UTC (what the repository sends as datetime2; the SQL declares it UTC)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _clip(text: Any) -> Optional[str]:
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 3] + "..."


class TxnRecorder:
    """Collects the events of ONE request in memory (with timestamps and durations); `flush()` persists them.

    `on_event(step, **info)` is the callback handed to services / `run_with_deadlock_retry`. It never raises.
    The recorder is NOT shared between threads: the DB Lab makes one per client."""

    def __init__(
        self, *, request_id: str, org_id: Optional[str], suspect_ms: Optional[int] = None,
        isolation_provider: Optional[Callable[[], str]] = None, now: Callable[[], dt.datetime] = _utcnow,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.request_id = request_id
        self.org_id = org_id
        self.suspect_ms = get_settings().lock_wait_suspect_ms if suspect_ms is None else suspect_ms
        self.events: list[dict[str, Any]] = []
        self._isolation_provider = isolation_provider
        self._isolation: Optional[str] = None
        self._isolation_read = False
        self._now, self._clock = now, clock
        self._t0: Optional[float] = None
        self._operation = "unknown"
        self.retries = 0
        self.finished = False  # committed()/rolled_back() already recorded

    # ------------------------------------------------------------------ recording
    @property
    def has_events(self) -> bool:
        return bool(self.events)

    def _isolation_level(self) -> Optional[str]:
        if not self._isolation_read:
            self._isolation_read = True
            try:
                self._isolation = self._isolation_provider() if self._isolation_provider else None
            except Exception:  # noqa: BLE001 - never let logging break the request
                self._isolation = None
        return self._isolation

    def _add(self, step: str, *, status: str, operation: Optional[str] = None, error_number: Optional[int] = None,
             message: Any = None, duration_ms: Optional[int] = None, retry_no: int = 0) -> None:
        if operation:
            self._operation = operation
        self.events.append({
            "request_id": self.request_id, "operation": self._operation, "step": step,
            "isolation_level": self._isolation_level(), "status": status, "error_number": error_number,
            "message": _clip(message), "duration_ms": duration_ms, "retry_no": retry_no, "created_at": self._now().isoformat(),
        })

    def _suspect(self, elapsed_ms: Optional[int], operation: Optional[str], retry_no: int) -> None:
        # INFERRED: the application only knows how long the call took, not that it waited for a lock.
        if elapsed_ms is not None and self.suspect_ms >= 0 and elapsed_ms >= self.suspect_ms:
            self._add("lock_wait_suspected", status="suspected", operation=operation, duration_ms=elapsed_ms, retry_no=retry_no,
                      message=f"attempt took {elapsed_ms} ms (threshold {self.suspect_ms} ms): a lock wait is SUSPECTED from the elapsed time; it was not observed")

    def on_event(self, step: str, **info: Any) -> None:
        """Hook for services and `run_with_deadlock_retry`. Unknown steps are ignored."""
        try:
            self._on_event(step, **info)
        except Exception:  # noqa: BLE001
            logger.exception("txn recorder failed on %s", step)

    def _on_event(self, step: str, **info: Any) -> None:
        op = info.get("operation")
        attempt = int(info.get("attempt") or 1)
        elapsed = info.get("elapsed_ms")
        if step == "txn_started":
            if self._t0 is None:
                self._t0 = self._clock()
            self._add("txn_started", status="started", operation=op, retry_no=attempt - 1,
                      message="attempt %d" % attempt if attempt > 1 else "attempt started")
        elif step in ("attempt_ok", "attempt_failed"):
            self._suspect(elapsed, op, attempt - 1)
        elif step in ("deadlock_retry", "deadlock_gave_up"):
            self._suspect(elapsed, op, attempt - 1)
            number = info.get("error_number")
            timeout = number == 1222
            self._add("lock_timeout_caught" if timeout else "deadlock_1205_caught", status="error", operation=op,
                      error_number=number or (1222 if timeout else 1205), duration_ms=elapsed, retry_no=attempt - 1,
                      message=("lock timeout" if timeout else "chosen as deadlock victim; SQL Server already rolled back this attempt")
                      + ": " + str(info.get("error") or ""))
            if step == "deadlock_retry":
                self.retries += 1
                self._add("retry_triggered", status="retrying", operation=op, retry_no=attempt,
                          message=f"retry {attempt}: the whole unit of work runs again in a new transaction")
        elif step == "business_rejected":
            self._add("business_rejected", status="rejected", operation=op, error_number=info.get("error_number"),
                      duration_ms=self._total_ms(), retry_no=self.retries,
                      message=f"{info.get('message') or 'rejected by a business rule'} (the procedure undid its own work; not an engine rollback)")

    def _total_ms(self) -> Optional[int]:
        return None if self._t0 is None else int((self._clock() - self._t0) * 1000)

    # ------------------------------------------------------------------ request outcome
    def committed(self) -> None:
        """The business transaction committed. Only recorded for requests that had instrumented work."""
        if not self.events or self.finished:
            return
        self._add("committed", status="committed", duration_ms=self._total_ms(), retry_no=self.retries,
                  message="transaction committed" + (f" after {self.retries} retr{'y' if self.retries == 1 else 'ies'}" if self.retries else ""))
        self.finished = True

    def rolled_back(self, exc: Optional[BaseException] = None, reason: Optional[str] = None) -> None:
        """The business transaction was rolled back because of `exc`/`reason`.

        After a business_rejected event nothing is added for an HTTP 4xx: the procedure already undid its work and the
        request-level rollback only discards an empty transaction; labelling it an engine rollback would be wrong."""
        if not self.events or self.finished:
            return
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and 400 <= status_code < 500 and any(e["step"] == "business_rejected" for e in self.events):
            self.finished = True
            return
        number = error_number_of(exc) if exc is not None else None
        if reason is None:
            if status_code is not None:
                reason = f"request failed with HTTP {status_code}: {getattr(exc, 'detail', '')}"
            elif exc is not None and is_deadlock(exc):
                reason = f"deadlock/lock timeout, retries exhausted: {exc}"
            else:
                reason = f"{type(exc).__name__}: {exc}" if exc is not None else "rolled back"
        self._add("rolled_back", status="rolled_back", error_number=number, duration_ms=self._total_ms(), retry_no=self.retries, message=reason)
        self.finished = True

    def drain(self) -> list[dict[str, Any]]:
        out, self.events = self.events, []
        return out


def report_rejected(on_event: Optional[Callable[..., None]], *, operation: str, error_number: Optional[int], message: Optional[str]) -> None:
    """A business rule refused the request (insufficient stock, not found, ...). Services call this so the log says
    "business_rejected" - NOT an engine rollback - without importing the recorder."""
    if on_event is not None:
        on_event("business_rejected", operation=operation, error_number=error_number, message=message)


def recorder_for(request_id: str, org_id: Optional[str], db: Any = None) -> TxnRecorder:
    """A recorder whose isolation level is read lazily (once) from `db`'s session when the first attempt starts."""
    provider = (lambda: txn_log_repository.get_isolation_level(db)) if db is not None else None
    return TxnRecorder(request_id=request_id, org_id=org_id, isolation_provider=provider)


def flush(recorder: TxnRecorder) -> int:
    """Persist the recorder's events through a SEPARATE autocommit connection. Never raises (a logging failure must not
    turn a successful request into an error); returns the number of rows written."""
    events = recorder.drain()
    if not events or not recorder.org_id:
        return 0
    try:
        log_db = clients.get_autocommit_connection()
        try:
            txn_log_repository.insert_events(log_db, org_id=recorder.org_id, events=events)
        finally:
            log_db.close()
        return len(events)
    except Exception:  # noqa: BLE001
        logger.exception("could not write %d txn_log events for request %s", len(events), recorder.request_id)
        return 0


# ---------------------------------------------------------------------- read side
def _clean(value: Optional[str], field: str, max_len: int) -> Optional[str]:
    if value is None or value == "":
        return None
    if len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters")
    return value


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError(f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    return limit, offset


def list_events(db, *, org_id: str, request_id: Optional[str] = None, operation: Optional[str] = None,
                step: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0,
                order: str = "desc") -> list[dict[str, Any]]:
    limit, offset = _page(limit, offset)
    if step not in (None, "") and step not in STEPS:
        raise ValidationError(f"step must be one of {list(STEPS)}")
    if order not in ("asc", "desc"):
        raise ValidationError("order must be 'asc' or 'desc'")
    return txn_log_repository.list_events(
        db, org_id=org_id, request_id=_clean(request_id, "request_id", 64), operation=_clean(operation, "operation", 60),
        step=step or None, status=_clean(status, "status", 20), limit=limit, offset=offset, oldest_first=order == "asc",
    )


def list_requests(db, *, org_id: str, request_id: Optional[str] = None, operation: Optional[str] = None,
                  outcome: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    limit, offset = _page(limit, offset)
    if outcome not in (None, "") and outcome not in OUTCOMES:
        raise ValidationError(f"outcome must be one of {list(OUTCOMES)}")
    return txn_log_repository.list_requests(
        db, org_id=org_id, request_id=_clean(request_id, "request_id", 64), operation=_clean(operation, "operation", 60),
        outcome=outcome or None, limit=limit, offset=offset,
    )
