"""AWS Lambda entrypoint for the FastAPI backend.

Wraps api/index.py's `app` (not core.fastapi_app.app directly): index.app
strips the "/api" prefix, so API Gateway/CloudFront can forward the frontend's
"/api/..." paths unchanged, exactly as Vercel does.

Lives in aws/ (not api/) on purpose: Vercel turns any .py under api/ that
binds a top-level `app`/`application`/`handler` into its own function (see
api/CLAUDE.md). build_lambda.py copies this file to the zip root at build time.

lifespan="off": the Supabase/Redis clients are created lazily on first use
(core/clients.py), so the startup/shutdown hooks aren't needed on Lambda.
"""
from mangum import Mangum

from index import app

handler = Mangum(app, lifespan="off")
