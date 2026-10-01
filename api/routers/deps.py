"""Shared FastAPI dependencies: current user + the per-request SQL Server connection."""
from __future__ import annotations

from typing import Iterator

from fastapi import HTTPException, Request

from core.clients import get_db_connection
from core.db import Db
from core.security import CurrentUser


def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_db() -> Iterator[Db]:
    """Per-request SQL Server connection: commit on success, rollback on exception, always closed."""
    db = get_db_connection()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
