"""Request id: one id per HTTP request, echoed in the `X-Request-ID` response header.

* A client-supplied `X-Request-ID` is honoured ONLY if it matches `^[A-Za-z0-9._-]{8,64}$` (so it is safe to store in the
  txn_log, to print in the UI and to put into a log line); anything else is ignored and a fresh uuid4 hex is used.
* The id is stored on `request.state.request_id`; `routers.deps.get_db` hands it to the request's TxnRecorder, so every
  txn_log row of the request carries it.
* Runs outermost (inside CORS) so the header is present on every response, including 401/400/500 ones.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

from services.txn_log_service import is_safe_request_id

HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        incoming = request.headers.get(HEADER)
        request_id = incoming if is_safe_request_id(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
