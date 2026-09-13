"""Redis-backed idempotency middleware for mutating requests.

Contract:
  * Every POST/PUT/PATCH request MUST include an `Idempotency-Key` header.
  * On first sight of a key, the request is processed normally; the response
    status code + body + headers are cached in Redis under
    `idempotency:{org_id}:{key}` for `IDEMPOTENCY_TTL_SECONDS` (default 24h).
  * On a repeat request with the same key (scoped per-org so two tenants can't
    collide), the cached response is returned immediately without re-running
    the handler.
  * A short-lived "in-flight" lock prevents two concurrent requests with the
    same key from both executing the handler (returns 409 to the loser).
"""
from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.clients import get_redis
from app.config import get_settings

MUTATING_METHODS = {"POST", "PUT", "PATCH"}
EXEMPT_PATHS = {"/auth/login", "/auth/register"}


def _cache_key(org_scope: str, idem_key: str) -> str:
    return f"idempotency:{org_scope}:{idem_key}"


def _lock_key(org_scope: str, idem_key: str) -> str:
    return f"idempotency-lock:{org_scope}:{idem_key}"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if request.method not in MUTATING_METHODS or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        if request.url.path.startswith("/api/inngest"):
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency-Key header is required for mutating requests"},
            )

        # Scope the cache key per-org (falls back to "anon" pre-auth, e.g. register)
        user = getattr(request.state, "user", None)
        org_scope = user.org_id if user else "anon"
        cache_key = _cache_key(org_scope, idem_key)
        lock_key = _lock_key(org_scope, idem_key)

        redis = get_redis()
        settings = get_settings()

        cached = await redis.get(cache_key)
        if cached is not None:
            payload = json.loads(cached)
            return JSONResponse(status_code=payload["status_code"], content=payload["body"])

        got_lock = await redis.set(lock_key, "1", nx=True, ex=30)
        if not got_lock:
            return JSONResponse(
                status_code=409,
                content={"detail": "A request with this Idempotency-Key is already being processed"},
            )

        try:
            response = await call_next(request)
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            try:
                body_json = json.loads(body_bytes.decode() or "null")
            except json.JSONDecodeError:
                body_json = body_bytes.decode(errors="replace")

            if response.status_code < 500:
                await redis.set(
                    cache_key,
                    json.dumps({"status_code": response.status_code, "body": body_json}),
                    ex=settings.idempotency_ttl_seconds,
                )

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        finally:
            await redis.delete(lock_key)
