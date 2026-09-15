# Infrastructure: Dockerfile & docker-compose

## What we did

**`Dockerfile`** — a multi-stage build:

- **Stage 1 (`builder`)**: `python:3.11-slim` + `build-essential`, creates a
  venv at `/opt/venv`, installs this project's dependencies from
  `pyproject.toml` into it.
- **Stage 2 (`runtime`)**: a fresh `python:3.11-slim` with no build
  toolchain, copies only the finished `/opt/venv` from the builder stage,
  copies the application source, creates and switches to a non-root
  `appuser`, and defines a container `HEALTHCHECK` that curls
  `GET /health`.
- Default `CMD` runs the FastAPI app via `uvicorn`; the same image can run
  the MCP stdio server instead by overriding `CMD` to
  `python mcp_gateway/server.py`.

**`docker-compose.yml`** — four services:

- **`redis`** (`redis:7-alpine`) — backs the idempotency middleware
  (`04-idempotency-redis.md`). Has its own healthcheck (`redis-cli ping`).
- **`inngest`** — the official Inngest Dev Server image, pointed at
  `http://api:8000/api/inngest` so it knows where to find and invoke this
  app's registered functions locally.
- **`api`** — this app, built from the `Dockerfile`, depends on `redis`
  being healthy before starting (`depends_on: redis: condition:
  service_healthy`).
- **`inngest-worker`** — a second copy of the exact same image, on a
  different port (8001).

## Why we did it

**Multi-stage build**: keeps the shipped runtime image free of compilers
and build headers (smaller image, smaller attack surface) while still
allowing native-dependency wheels to compile correctly in the build stage.
This is a standard, low-risk choice for a Python service with any C-backed
dependencies — not specific to this app's business logic, but worth
stating so a future change doesn't collapse it back into a single stage
"to simplify" and silently bloat the image.

**Non-root `appuser`**: running the container process as root is an
avoidable privilege-escalation risk if the container is ever compromised
(a dependency vulnerability, a request-smuggling bug, etc.) — there's no
reason this specific app needs root inside its container, so it doesn't
run as root.

**`HEALTHCHECK` hitting `/health`**: `docker compose` and any orchestrator
(Kubernetes readiness/liveness probes, if this is ever deployed there) need
a real signal for "is this container actually serving traffic," not just
"did the process start." `/health` (see `04-idempotency-redis.md` and
`app/main.py`) independently checks both Redis and Supabase connectivity,
so a container that's up but can't reach its dependencies is correctly
reported unhealthy rather than falsely "running."

**Why the Inngest Dev Server is in the compose file at all**: the spec for
this ladder step explicitly required local background-job routing without
depending on Inngest's hosted cloud service — the dev server is Inngest's
own tool for exactly this, and pointing it at `api:8000/api/inngest` lets
you `docker compose up` and get a fully working local reproduction of the
production job-triggering flow (an HTTP event fired at `/api/inngest`,
dispatched to the registered `financial_advisor_job` function) with no
external account or network dependency.

**`api` depends on `redis` being healthy, not just started**: the
idempotency middleware (`04-idempotency-redis.md`) needs a working Redis
connection to function correctly for any mutating request. Starting the
`api` container before Redis has actually finished booting (not just been
launched) would produce confusing early-request failures purely due to
startup-ordering, unrelated to any real bug — `condition: service_healthy`
avoids that class of flaky failure.

**Why `inngest-worker` exists as a near-duplicate of `api`**: the Inngest
Python SDK's execution model here isn't a separate polling worker process
— Inngest's dev server (or its cloud) calls *back into* the app's
`/api/inngest` HTTP endpoint to invoke each step, meaning "the worker" and
"the API" are the same running FastAPI process (`app.main:app`) in this
architecture. `inngest-worker` is included, running the identical image on
a different port, specifically so this compose file demonstrates the shape
a real deployment would take if you wanted to scale
Inngest-invoked/background traffic independently from user-facing API
traffic (e.g. different replica counts, different resource limits) behind
a load balancer or separate service — without that meaning two different
codebases or images to maintain. If you don't need that separation
locally, running just `api` is sufficient; `inngest-worker` exists as a
topology example, not a hard local-dev requirement.

## Running it

```bash
cp .env.example .env   # fill in real Supabase/OpenAI values
docker compose up --build
```

- Inngest Dev Server UI: `http://localhost:8288`
- FastAPI OpenAPI docs: `http://localhost:8000/docs`

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

(You'll need a real Redis instance reachable at `REDIS_URL` for the
idempotency middleware to function outside of `fakeredis`-backed tests.)

## What this does NOT cover

This compose file is a **local development / demo topology**, not a
production deployment manifest — there's no TLS termination, no secrets
management beyond a plain `.env` file, no resource limits, and no restart
policies configured. Treat `docker-compose.yml` as the fastest path to "run
the whole stack locally and see it work end-to-end," and build a real
production deployment (Kubernetes manifests, a managed Redis/Postgres, a
proper secrets store) as a deliberate separate effort rather than assuming
this file scales up as-is.
