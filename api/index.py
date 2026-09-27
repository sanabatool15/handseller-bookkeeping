"""Vercel Python Serverless Function entrypoint.

Vercel treats any top-level .py file directly under api/ as a function; this
is the only one, and it wraps the real FastAPI app (api/app/main.py).

Root vercel.json rewrites every /api/* request to this function, and
rewrites preserve the original request path in the ASGI scope -- so this
function sees e.g. "/api/auth/login", while every router inside
api/app/main.py is registered unprefixed ("/auth", "/sales", ...), exactly
as it is for the standalone (docker/uvicorn) deployment.

A FastAPI/Starlette `Mount` was tried first but rejected: mounting only sets
scope["root_path"], it does NOT strip scope["path"] the way older Starlette
versions did (verified against the installed version) -- middleware/auth.py
and middleware/idempotency.py both compare `request.url.path` against
hardcoded public-path strings like "/health"/"/auth/login", and those
compare against the FULL path, so under a Mount every one of them would
have kept 401ing on paths that must be public. Stripping the "/api" prefix
directly off scope["path"] before it ever reaches the app keeps every
existing path-based check in app/main.py's middleware working unchanged.
"""
from __future__ import annotations

from app.main import app as _app

API_PREFIX = "/api"


async def app(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith(API_PREFIX):
        scope["path"] = scope["path"][len(API_PREFIX):] or "/"
    await _app(scope, receive, send)
