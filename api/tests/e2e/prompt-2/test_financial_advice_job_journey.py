"""Scenario 4: financial-advice background job lifecycle via REAL Inngest
event delivery (not an in-process step simulation).

Per CLAUDE.md rule 3 ("Agent tasks never run synchronously inside an HTTP
request handler") and specs/05-background-jobs-inngest.md, triggering the
job must return 202 + job_id immediately, and the actual work must be
driven by the live Inngest dev server calling back into this app's
`/api/inngest` endpoint (mounted in `app/main.py`), which in turn runs
`jobs/financial_agent_job.py`'s step function against the real Supabase
instance. This test requires:
  - `INNGEST_BASE_URL` (default http://localhost:8288) reachable, with the
    dev server registered against this app's `/api/inngest` endpoint (i.e.
    `docker compose up`, which runs both), and
  - a real Postgres/Supabase instance with `sql/schema.sql` applied.

It intentionally does NOT import or call `jobs/financial_agent_job.py`'s
step functions directly -- that would be simulating the job in-process,
which the task explicitly calls out as the thing to stop doing. Instead it
only ever talks to the app's real HTTP surface and waits for the real
worker to move the job to "completed".
"""
from __future__ import annotations

import time
import uuid

import httpx
import pytest


def _unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, cleanup, tag: str):
    email = _unique_email(tag)
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-1", "full_name": "E2E Tester", "org_name": f"Org-{tag}"},
        headers={"Idempotency-Key": f"reg-{tag}"},
    )
    assert resp.status_code == 201, f"register failed: {resp.status_code} {resp.text}"
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    cleanup.track_row("users", user_id, org_id)
    cleanup.track_row("orgs", org_id)
    return body["access_token"], org_id, user_id


def _inngest_dev_server_reachable() -> bool:
    import os

    base_url = os.environ.get("INNGEST_BASE_URL", "http://localhost:8288")
    try:
        httpx.get(base_url, timeout=2.0)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(
    not _inngest_dev_server_reachable(),
    reason="Real Inngest dev server not reachable at INNGEST_BASE_URL; this scenario requires live event "
    "delivery and is explicitly not simulated in-process. See RESULTS.md for the connection error.",
)
def test_financial_advice_job_completes_via_real_inngest(client, cleanup):
    token, org_id, _ = _register(client, cleanup, "advice-job")
    headers = {"Authorization": f"Bearer {token}"}

    sale = client.post(
        "/sales", json={"amount": 500.0, "category": "retail"},
        headers={**headers, "Idempotency-Key": "advice-job-sale"},
    )
    assert sale.status_code == 201, sale.text
    cleanup.track_row("sales", sale.json()["id"], org_id)

    trigger = client.post(
        "/agent-jobs/financial-advice", headers={**headers, "Idempotency-Key": "advice-job-trigger"}
    )
    assert trigger.status_code == 202, trigger.text
    body = trigger.json()
    job_id = body["job_id"]
    cleanup.track_row("agent_jobs", job_id, org_id)
    assert body["status"] in ("pending", "queued", "processing")

    # Poll the real status endpoint -- backed by the real Postgres row that
    # the real Inngest worker updates as it executes each step.
    final_status = None
    for _ in range(60):
        status_resp = client.get(f"/agent-jobs/{job_id}", headers=headers)
        assert status_resp.status_code == 200
        final_status = status_resp.json()
        if final_status.get("status") in ("completed", "failed"):
            break
        time.sleep(1)

    assert final_status is not None
    assert final_status.get("status") == "completed", f"job did not complete in time: {final_status}"
    result = final_status.get("result")
    assert result is not None
    assert result.get("source") in ("openai_agent", "rule_based_fallback")

    # Cross-tenant: another org must never see this job by id.
    other_token, _other_org_id, _ = _register(client, cleanup, "advice-job-other")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    cross_tenant = client.get(f"/agent-jobs/{job_id}", headers=other_headers)
    assert cross_tenant.status_code == 404, cross_tenant.text
