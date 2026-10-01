"""core/db.py against a stub DB-API connection (no ODBC driver / SQL Server needed)."""
from __future__ import annotations

import datetime as dt
import decimal
import uuid

import pytest

from core.db import (
    Db, UniqueViolationError, is_deadlock, is_unique_violation, normalise_row, run_with_deadlock_retry, transaction,
)


class StubCursor:
    def __init__(self, conn):
        self.conn, self.description, self.rowcount, self._rows = conn, None, -1, []

    def execute(self, sql, params=()):
        self.conn.executed.append((sql, params))
        if self.conn.raise_on:
            raise self.conn.raise_on
        self.description, self._rows, self.rowcount = self.conn.result_desc, self.conn.result_rows, 3

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class StubConn:
    def __init__(self, desc=None, rows=(), raise_on=None):
        self.result_desc, self.result_rows, self.raise_on = desc, list(rows), raise_on
        self.executed, self.commits, self.rollbacks, self.closed = [], 0, 0, False

    def cursor(self):
        return StubCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_row_normalisation():
    u = uuid.uuid4()
    row = normalise_row(
        ["id", "amt", "d", "ts", "n"],
        [u, decimal.Decimal("12.50"), dt.date(2026, 1, 2), dt.datetime(2026, 1, 2, 3, 4, 5), None],
    )
    assert row == {"id": str(u), "amt": 12.5, "d": "2026-01-02", "ts": "2026-01-02T03:04:05", "n": None}
    assert isinstance(row["amt"], float)


def test_query_query_one_execute_pass_params_and_normalise():
    conn = StubConn(desc=[("id",), ("amount",)], rows=[("a", decimal.Decimal("1.10"))])
    db = Db(conn)
    assert db.query("SELECT 1 WHERE x = ?", (5,)) == [{"id": "a", "amount": 1.1}]
    assert db.query_one("SELECT 1") == {"id": "a", "amount": 1.1}
    assert conn.executed[0] == ("SELECT 1 WHERE x = ?", (5,))
    assert db.execute("UPDATE t SET a = ?", ["x"]) == 3
    conn.result_rows = []
    assert db.query_one("SELECT 1") is None
    conn.result_desc = None
    assert db.query("UPDATE t SET a = 1") == []


def test_transaction_commits_on_success():
    conn = StubConn()
    with transaction(Db(conn)):
        pass
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_transaction_rolls_back_and_reraises_on_error():
    conn = StubConn()
    with pytest.raises(ValueError):
        with transaction(Db(conn)):
            raise ValueError("boom")
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_unique_violation_translated():
    err = Exception("23000", "[23000] Violation of UNIQUE KEY constraint 'UQ_users_email' (2627)")
    assert is_unique_violation(err)
    with pytest.raises(UniqueViolationError):
        Db(StubConn(raise_on=err)).execute("INSERT ...")
    assert not is_unique_violation(Exception("something else 1205"))


class Deadlock(Exception):
    def __init__(self):
        super().__init__("40001", "Transaction was deadlocked ... (1205)")


def test_deadlock_detection():
    assert is_deadlock(Deadlock())
    assert is_deadlock(Exception("HYT00", "Lock request time out period exceeded. (1222)"))
    assert not is_deadlock(Exception("22003", "Arithmetic overflow (8115)"))


def test_deadlock_retry_succeeds_on_second_attempt():
    calls, events = [], []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise Deadlock()
        return "ok"

    assert run_with_deadlock_retry(fn, on_event=lambda step, **i: events.append(step), backoff_seconds=0) == "ok"
    assert len(calls) == 2 and events == ["deadlock_retry"]


def test_deadlock_retry_gives_up_after_retries():
    calls, events = [], []

    def fn():
        calls.append(1)
        raise Deadlock()

    with pytest.raises(Deadlock):
        run_with_deadlock_retry(fn, retries=2, on_event=lambda step, **i: events.append(step), backoff_seconds=0)
    assert len(calls) == 3  # first try + 2 retries
    assert events == ["deadlock_retry", "deadlock_retry", "deadlock_gave_up"]


def test_non_deadlock_error_not_retried():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        run_with_deadlock_retry(fn, backoff_seconds=0)
    assert len(calls) == 1
