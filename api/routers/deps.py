"""Shared FastAPI dependencies: current user, the per-request SQL Server connection and the per-request txn recorder."""
from __future__ import annotations

import uuid
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from core.clients import get_db_connection
from core.db import Db
from core.security import CurrentUser
from services import txn_log_service
from services.txn_log_service import TxnRecorder


def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_db(request: Request) -> Iterator[Db]:
    """Per-request SQL Server connection: commit on success, rollback on exception, always closed.

    Also owns the request's `TxnRecorder` (stored on `request.state.txn_recorder`; routers pass `recorder.on_event` to
    services). ORDER MATTERS: the recorder is told about the commit/rollback only AFTER it really happened, and its
    events are flushed in `finally` AFTER the business connection is closed, through a separate autocommit
    connection - so a rolled-back request still leaves its log (specs/15 section 8). The flush never raises."""
    db = get_db_connection()
    user = getattr(request.state, "user", None)
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    recorder = txn_log_service.recorder_for(request_id, getattr(user, "org_id", None), db)
    request.state.txn_recorder = recorder
    try:
        try:
            yield db
            db.commit()
        except BaseException as exc:
            try:
                db.rollback()
            finally:
                recorder.rolled_back(exc)
            raise
        else:
            recorder.committed()
    finally:
        db.close()
        txn_log_service.flush(recorder)


# `scope="function"`: the exit code above (commit/rollback + log flush) runs right after the route function returns and
# BEFORE the response is sent. FastAPI's default ("request") runs it AFTER the response was sent, so a client could get
# its 201 before the commit happened (and a failing commit could no longer change the response). tests/unit/test_txn_log
# guards that every router uses this.
DB = Depends(get_db, scope="function")


def get_txn_recorder(request: Request, db: Db = DB) -> TxnRecorder:
    """The recorder of this request (created by `get_db`, which is a dependency of this one so it exists)."""
    return request.state.txn_recorder
