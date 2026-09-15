"""Authentication middleware.

Verifies the `Authorization: Bearer <jwt>` header on every request (except a
small allowlist of public paths), decodes it into a `CurrentUser`, and stashes
it on `request.state.user` so routers/services can read it without re-parsing
the header. Multi-tenancy scoping downstream relies on `request.state.user.org_id`
being trustworthy, so this MUST run before any route handler executes.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security import TokenError, decode_access_token

PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/register",
    "/api/inngest",  # Inngest calls this endpoint with its own signing-key auth
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/api/inngest"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing or malformed Authorization header"})

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            current_user = decode_access_token(token)
        except TokenError as exc:
            return JSONResponse(status_code=401, content={"detail": f"Invalid token: {exc}"})

        request.state.user = current_user
        return await call_next(request)
