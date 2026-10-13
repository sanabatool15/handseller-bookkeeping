"""Idempotency middleware for mutating requests (answers are saved in SQL Server, no Redis).

Contract:
  * Every POST/PUT/PATCH request MUST include an `Idempotency-Key` header.
  * First time a key is seen: the request runs normally and its answer (status + body) is saved in the
    `idempotency_keys` table for `IDEMPOTENCY_TTL_SECONDS` (default 24h). Key + business (org) together are unique.
  * Same key again: the saved answer is returned at once, the handler does not run again.
  * Same key while the first request is still running: answer 409.
  * Server errors (5xx) are never saved, so the client can retry.
"""
from __future__ import annotations

import json

from fastapi.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import get_settings
from services import idempotency_service

MUTATING_METHODS = {"POST", "PUT", "PATCH"}
EXEMPT_PATHS = {"/auth/login", "/auth/register"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if request.method not in MUTATING_METHODS or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency-Key header is required for mutating requests"},
            )
        if len(idem_key) > 200:
            return JSONResponse(status_code=400, content={"detail": "Idempotency-Key is too long (max 200 characters)"})

        # Scope per business (falls back to "anon" before login)
        user = getattr(request.state, "user", None)
        org_scope = str(user.org_id) if user else "anon"
        ttl = get_settings().idempotency_ttl_seconds

        state, cached = await run_in_threadpool(idempotency_service.begin, org_scope, idem_key, ttl)
        if state == "cached":
            return JSONResponse(status_code=cached["status_code"], content=cached["body"])
        if state == "in_progress":
            return JSONResponse(
                status_code=409,
                content={"detail": "A request with this Idempotency-Key is already being processed"},
            )

        try:
            response = await call_next(request)
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            if response.status_code < 500:
                try:
                    body_json = json.loads(body_bytes.decode() or "null")
                except json.JSONDecodeError:
                    body_json = body_bytes.decode(errors="replace")
                await run_in_threadpool(idempotency_service.finish, org_scope, idem_key, response.status_code, body_json)
            else:
                await run_in_threadpool(idempotency_service.abandon, org_scope, idem_key)

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except BaseException:
            await run_in_threadpool(idempotency_service.abandon, org_scope, idem_key)
            raise
