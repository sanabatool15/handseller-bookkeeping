"""End-to-end test of the full financial-advisor workflow against a REAL
Inngest Dev Server + real (or local) Supabase/Postgres + real Redis.

This is intentionally NOT runnable in CI/sandbox environments without live
infrastructure: it requires `docker compose up` (see docker-compose.yml) to
have Redis, the Inngest dev server, and the FastAPI app all running, plus a
reachable Supabase/Postgres instance with `sql/schema.sql` applied.

Per the task's own guidance ("tests/e2e can be best-effort/skippable if it
genuinely requires live Inngest/Docker infra"), this whole module is skipped
unless the environment variable RUN_E2E=1 is set, so `pytest` runs clean by
default while still documenting exactly what a full e2e run would exercise.
"""
from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "1",
    reason="Requires live docker-compose stack (FastAPI + Redis + Inngest dev server + Supabase). Set RUN_E2E=1 to run.",
)

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")


def test_end_to_end_financial_advice_job_completes():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        register = client.post(
            "/auth/register",
            json={"email": "e2e@example.com", "password": "hunter2pass", "full_name": "E2E", "org_name": "E2E Co"},
            headers={"Idempotency-Key": "e2e-register"},
        )
        assert register.status_code == 201
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        client.post(
            "/sales",
            json={"amount": 500.0, "category": "retail"},
            headers={**headers, "Idempotency-Key": "e2e-sale-1"},
        )

        trigger = client.post(
            "/agent-jobs/financial-advice",
            headers={**headers, "Idempotency-Key": "e2e-job-1"},
        )
        assert trigger.status_code == 202
        job_id = trigger.json()["job_id"]

        # Poll until the Inngest dev server has driven the job to completion.
        import time

        for _ in range(30):
            status = client.get(f"/agent-jobs/{job_id}", headers=headers)
            if status.json().get("status") == "completed":
                assert status.json()["result"] is not None
                return
            time.sleep(1)

        pytest.fail("Job did not complete within 30s against the live Inngest dev server")
