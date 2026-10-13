"""Client factories: SQL Server connections (`get_db_connection`, `get_autocommit_connection`)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator, Optional

from core.config import build_mssql_connection_string, get_settings
from core.db import Db, connect, transaction

_db_factory: Optional[Callable[[], Db]] = None
_autocommit_factory: Optional[Callable[[], Db]] = None


def get_db_connection() -> Db:
    """Return a NEW SQL Server `Db` (one per request/unit of work; caller closes it)."""
    if _db_factory is not None:
        return _db_factory()
    return connect(build_mssql_connection_string(get_settings()))


def set_db_factory(factory: Optional[Callable[[], Db]]) -> None:
    """Test/dependency-injection hook; pass None to restore the real pyodbc factory."""
    global _db_factory
    _db_factory = factory


def get_autocommit_connection() -> Db:
    """Return a NEW, SEPARATE SQL Server connection in AUTOCOMMIT mode (caller closes it).

    Used to write the transaction log (`txn_log`): every statement on it commits on its own, completely independent
    of the business transaction running on another connection, so the log of a request that was rolled back
    survives the rollback (docs/SQL_TRANSACTIONS.md). Never use it for business writes."""
    if _autocommit_factory is not None:
        return _autocommit_factory()
    return connect(build_mssql_connection_string(get_settings()), autocommit=True)


def set_autocommit_factory(factory: Optional[Callable[[], Db]]) -> None:
    """Test hook for `get_autocommit_connection`; pass None to restore the real pyodbc factory."""
    global _autocommit_factory
    _autocommit_factory = factory


@contextmanager
def db_session() -> Iterator[Db]:
    """One connection + one transaction for code that runs OUTSIDE a FastAPI request
    (scripts): commit on success, rollback on any
    exception (re-raised), always closed. Not for use inside request handlers (use
    `routers.deps.get_db` there)."""
    db = get_db_connection()
    try:
        with transaction(db):
            yield db
    finally:
        db.close()
