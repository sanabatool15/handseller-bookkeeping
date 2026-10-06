# Deployment layout (Vercel)

This directory (`api/`) is the entire backend, deployed as a single Vercel
Python Serverless Function. Everything below assumes your shell's cwd is
`api/`, not the repo root — the repo root is the Next.js frontend, and
`api/` is a self-contained Python project inside it.

`api/index.py` is the only top-level `.py` file directly in `api/` — Vercel
treats any such file as a function entrypoint, so it must stay the single
one. It imports the real app from `core/fastapi_app.py` and strips the `/api`
prefix off the incoming path before dispatching to it; the root
`vercel.json` rewrites every `/api/*` request to this function. Do not add
another top-level `.py` file in `api/` unless you intend it to become a
second, separate serverless function.

**Only `api/index.py` may define a top-level `app`/`application`/`handler`
binding anywhere under `api/`.** Vercel's Python runtime scans every `.py`
file under `api/` for one of those names and turns each match into its own
separate serverless function — this is NOT limited to specially-named
top-level files or to `app/`/`src/` subfolders specifically; renaming the
backend package folder from `app/` to `core/` alone did not stop it. The
real FastAPI app used to live at `api/app/main.py`, then `api/core/main.py`
— both times Vercel treated that file as a *second, independent* entrypoint
alongside `api/index.py` (both define a top-level `app`), built two
competing functions (visible in the build log as repeated
dependency-install cycles), and the resulting routing ambiguity broke the
deployed site's `/` route entirely, even though the Next.js build itself
succeeded. The fix was renaming the FILE to `api/core/fastapi_app.py` — a
name outside Vercel's reserved entrypoint list
(app.py/index.py/server.py/main.py/wsgi.py/asgi.py). **Never name the real
app's module `main.py` (or any of that list) anywhere under `api/`, and
never give any other file under `api/` a top-level `app`/`application`/
`handler` binding** — that reintroduces the exact collision (see Vercel's
own docs: https://vercel.com/docs/functions/runtimes/python and
https://vercel.com/docs/functions/runtimes/python/api-directory — though
note the observed behavior here is broader than what those pages state
explicitly).

**`api/index.py` inserts its own directory onto `sys.path` before importing
`core.fastapi_app`.** Vercel's Python runtime imports `api/index.py` via
`importlib` directly (not by running it as a script), so Python does NOT
auto-add the file's own directory to `sys.path` the way it would for a
normally-executed script — the sibling `core/` package was unimportable as
a bare `core` without this (`ModuleNotFoundError: No module named 'core'`,
confirmed against a real deployment log). Do not remove that
`sys.path.insert(0, ...)` line, and if you ever change how the entrypoint
resolves the real app, re-verify with an actual Vercel deployment, not just
a local `uvicorn`/`pytest` run — this class of bug does not reproduce
locally since local runs execute `index.py` in a context where the cwd
already resolves `core`.

`api/requirements.txt` and `api/pyproject.toml`'s `[project.dependencies]`
list the same dependencies in two formats — Vercel's Python builder reads
either `pyproject.toml`, `requirements.txt`, or a `Pipfile` (it actually
prefers `pyproject.toml` when present, which is what originally exposed the
package-collision bug below). Keep both in sync when either changes; local
Docker/dev tooling uses `requirements.txt` directly.

**Do not add a `[build-system]`/`[tool.setuptools] packages = [...]`
section back to `pyproject.toml`.** It used to declare all 8 backend
subpackages, and Vercel's `uv`-based builder read that as 8 separate
installable workspace members, installing dependencies once per package
(visible in the build log as repeated "Installing required dependencies"
cycles) instead of once for the whole app. This project is never `pip
install`ed as a distributable package — pytest resolves imports via `cwd`,
no editable install needed.

## Vercel project dashboard settings

The **Framework Preset** setting on the Vercel project is sticky — it is
set once and reused for every deployment, not re-detected on each push. If
it was set to something other than "Next.js" (e.g. from when this project
was Python-only, pre-restructure), the frontend build silently never runs,
regardless of what the repo contains. If `/` 404s in production but
`next build` succeeds locally, check **Settings → General → Framework
Preset** (must be "Next.js") and **Root Directory** (must be blank/`.`)
before assuming it's a code problem.
