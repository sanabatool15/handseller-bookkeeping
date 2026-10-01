"""Shared FastAPI dependencies: current user + supabase client accessors."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException, Request
from supabase import Client

from core.clients import get_db_connection, get_supabase
from core.db import Db
from core.security import CurrentUser


def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_db() -> Client:
    return get_supabase()


def get_sql_db() -> Iterator[Db]:
    """Per-request SQL Server connection: commit on success, rollback on exception.

    Transition note (specs/13): `get_db` above is the legacy Supabase client still used
    by sales/expenses/agent routes; it is replaced slice by slice and renamed at the end.
    """
    db = get_db_connection()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
