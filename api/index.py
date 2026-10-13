"""Entry point: `uv run uvicorn index:app --reload --port 8000`.

The website calls `/api/...`. This wrapper removes the `/api` prefix and passes the request to the real FastAPI app
(`core/fastapi_app.py`), whose routes have no prefix ("/auth", "/sales", ...).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the sibling `core` package importable when this file is loaded by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.fastapi_app import app as _app

API_PREFIX = "/api"


async def app(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith(API_PREFIX):
        scope["path"] = scope["path"][len(API_PREFIX):] or "/"
    await _app(scope, receive, send)
