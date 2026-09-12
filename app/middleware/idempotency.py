"""Idempotency middleware for mutating (POST/PUT/PATCH) requests.

Flow:
  1. For POST/PUT/PATCH requests, require an `Idempotency-Key` header (400 if
     missing).
  2. Look up (key, user_id) in idempotency_keys.
     - Cache hit: return the stored response_body/status_code immediately,
       short-circuiting before the route handler runs.
     - Cache miss: let the request proceed, capture the response, persist it,
       then return it.
"""
import json

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.auth import decode_token
from app.repository import idempotency_repository

MUTATING_METHODS = {"POST", "PUT", "PATCH"}

# Paths exempt from idempotency enforcement (auth not required / not mutating
# business data).
EXEMPT_PATH_PREFIXES = ("/docs", "/openapi.json", "/redoc", "/health")


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in MUTATING_METHODS or any(
            request.url.path.startswith(p) for p in EXEMPT_PATH_PREFIXES
        ):
            return await call_next(request)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Missing required 'Idempotency-Key' header"},
            )

        user_id = self._extract_user_id(request)
        if user_id is None:
            # Let auth-less/invalid-token requests fall through to normal
            # auth handling in the route dependency (which will 401/403).
            return await call_next(request)

        cached = idempotency_repository.get_idempotency_record(key=idempotency_key, user_id=user_id)
        if cached is not None:
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["response_body"],
            )

        response = await call_next(request)

        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk

        try:
            response_body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_body = {}

        if 200 <= response.status_code < 300:
            idempotency_repository.create_idempotency_record(
                key=idempotency_key,
                user_id=user_id,
                response_body=response_body,
                status_code=response.status_code,
            )

        return Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except Exception:
            return None
        return payload.get("sub")
