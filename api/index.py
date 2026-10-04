"""Vercel Python Serverless Function entrypoint.

Vercel treats any top-level .py file directly under api/ as a function; this
is the only one, and it wraps the real FastAPI app (api/core/fastapi_app.py).

Root vercel.json rewrites every /api/* request to this function, and
rewrites preserve the original request path in the ASGI scope -- so this
function sees e.g. "/api/auth/login", while every router inside
api/core/fastapi_app.py is registered unprefixed ("/auth", "/sales", ...),
exactly as it is for the standalone (docker/uvicorn) deployment.

A FastAPI/Starlette `Mount` was tried first and rejected: mounting only sets
scope["root_path"], it does NOT strip scope["path"] the way older Starlette
versions did (verified against the installed version) -- middleware/auth.py
and middleware/idempotency.py both compare `request.url.path` against
hardcoded public-path strings like "/health"/"/auth/login", and those
compare against the FULL path, so under a Mount every one of them would
have kept 401ing on paths that must be public. Stripping the "/api" prefix
directly off scope["path"] before it ever reaches the app keeps every
existing path-based check in core/fastapi_app.py's middleware working
unchanged.

The real FastAPI app deliberately does NOT live in a file named
app.py/index.py/server.py/main.py/wsgi.py/asgi.py anywhere under api/
(verified: it used to be api/app/main.py, then api/core/main.py -- both
still broke the deployment). Vercel's Python runtime scans every .py file
under api/ for a top-level `app`/`application`/`handler` binding and turns
each match into its own separate function, regardless of which folder it's
in -- it is NOT limited to specially-named top-level files. With two such
files (this one plus the real app's module), Vercel built two competing
functions (visible in the build log as repeated dependency-install cycles)
and the resulting routing ambiguity 404'd the deployed site's "/" route
entirely, even though Next.js itself built fine. Renaming the folder
(app/ -> core/) alone did NOT fix this -- only api/index.py may define a
top-level `app`. If you rename or add a module that defines the real
FastAPI app, name the FILE something outside that reserved list.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Vercel's Python runtime imports this file directly via importlib without
# adding its own directory to sys.path, so the sibling `core` package
# (api/core/) is NOT importable as a bare "core" without this -- verified via
# the deployed traceback: "ModuleNotFoundError: No module named 'core'".
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.fastapi_app import app as _app

API_PREFIX = "/api"
# The Inngest handler is registered at the full "/api/inngest" path in
# core/fastapi_app.py, and AuthMiddleware/IdempotencyMiddleware exempt that
# full path -- so it must NOT have the "/api" prefix stripped like every
# other route (stripped, it would become "/inngest": no route, and a 401 from
# AuthMiddleware that Inngest reports as "Unauthorized response from URL").
INNGEST_PREFIX = "/api/inngest"


async def app(scope, receive, send):
    if (
        scope["type"] == "http"
        and scope["path"].startswith(API_PREFIX)
        and not scope["path"].startswith(INNGEST_PREFIX)
    ):
        scope["path"] = scope["path"][len(API_PREFIX):] or "/"
    await _app(scope, receive, send)
