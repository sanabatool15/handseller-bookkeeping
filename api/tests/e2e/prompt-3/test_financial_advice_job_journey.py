"""Scenario 4: financial-advice background job lifecycle via REAL Inngest
event delivery (not an in-process step simulation).

Real-infra e2e (see PROMPT_V3.md): narrated, self-explanatory-on-failure
version of prompt-2's financial-advice job journey. Still requires a real,
reachable Inngest dev server (INNGEST_BASE_URL) and does not simulate the
job in-process -- if the dev server isn't reachable the test is skipped
(never faked) with the reason recorded.
"""
from __future__ import annotations

import time
import uuid

import httpx
import pytest

import uuid


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def expect(condition: bool, *, request_desc: str, response, message: str) -> None:
    if condition:
        return
    if response is not None:
        detail = (
            f"{message}\n"
            f"  request sent:      {request_desc}\n"
            f"  response status:   {response.status_code}\n"
            f"  response body:     {response.text}"
        )
    else:
        detail = f"{message}\n  request sent: {request_desc}"
    raise AssertionError(detail)


def _register(client, cleanup, story, tag: str):
    email = unique_email(tag)
    payload = {"email": email, "password": "correct-horse-1", "full_name": "E2E Tester", "org_name": f"Org-{tag}"}
    story.say(f"Registering user {email!r} for org 'Org-{tag}'")
    resp = client.post("/auth/register", json=payload, headers={"Idempotency-Key": f"reg-{tag}"})
    expect(resp.status_code == 201, request_desc=f"POST /auth/register json={payload}", response=resp,
           message="register should return 201")
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
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
    "delivery and is explicitly not simulated in-process. See PROMPT_V3.md / test_run.log for the connection error.",
)
def test_financial_advice_job_completes_via_real_inngest(client, cleanup, story):
    token, org_id, _ = _register(client, cleanup, story, "advice-job")
    headers = {"Authorization": f"Bearer {token}"}

    sale_payload = {"amount": 500.0, "category": "retail"}
    story.say(f"POSTing a sale of amount {sale_payload['amount']} to give the advisor something to analyze")
    sale = client.post("/sales", json=sale_payload, headers={**headers, "Idempotency-Key": "advice-job-sale"})
    expect(sale.status_code == 201, request_desc=f"POST /sales json={sale_payload}", response=sale,
           message="creating the sale should return 201")
    cleanup.track_row("sales", sale.json()["id"], org_id, **sale_payload)

    story.say("Triggering POST /agent-jobs/financial-advice -- must return 202 immediately (no sync agent work in the handler)")
    trigger = client.post("/agent-jobs/financial-advice", headers={**headers, "Idempotency-Key": "advice-job-trigger"})
    expect(trigger.status_code == 202, request_desc="POST /agent-jobs/financial-advice", response=trigger,
           message="triggering the job should return 202 Accepted immediately, per CLAUDE.md rule 3")
    body = trigger.json()
    job_id = body["job_id"]
    story.say(f"Got job_id={job_id}, initial status={body.get('status')}")
    cleanup.track_row("agent_jobs", job_id, org_id)
    expect(body["status"] in ("pending", "queued", "processing"), request_desc="POST /agent-jobs/financial-advice",
           response=trigger, message=f"initial job status should be pending/queued/processing, got {body.get('status')!r}")

    story.say(f"Polling GET /agent-jobs/{job_id} until the real Inngest worker drives it to completed/failed (up to 60s)")
    final_status = None
    for i in range(60):
        status_resp = client.get(f"/agent-jobs/{job_id}", headers=headers)
        expect(status_resp.status_code == 200, request_desc=f"GET /agent-jobs/{job_id} (poll #{i})", response=status_resp,
               message="polling the job status should return 200")
        final_status = status_resp.json()
        story.say(f"  poll #{i}: status={final_status.get('status')}")
        if final_status.get("status") in ("completed", "failed"):
            break
        time.sleep(1)

    expect(final_status is not None, request_desc=f"GET /agent-jobs/{job_id}", response=None,
           message="should have received at least one poll response")
    expect(final_status.get("status") == "completed", request_desc=f"GET /agent-jobs/{job_id} (final poll)", response=None,
           message=f"job did not complete in time (60s); last known status: {final_status}")
    result = final_status.get("result")
    expect(result is not None, request_desc=f"GET /agent-jobs/{job_id} (final poll)", response=None,
           message=f"completed job should carry a result; final_status={final_status}")
    expect(result.get("source") in ("openai_agent", "rule_based_fallback"), request_desc=f"GET /agent-jobs/{job_id} (final poll)",
           response=None, message=f"result.source should be openai_agent or rule_based_fallback, got {result.get('source')!r}")
    story.say(f"Job completed with source={result.get('source')!r}")

    story.say("Registering a second, unrelated org to confirm it cannot see org A's job by id")
    other_token, _other_org_id, _ = _register(client, cleanup, story, "advice-job-other")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    cross_tenant = client.get(f"/agent-jobs/{job_id}", headers=other_headers)
    expect(cross_tenant.status_code == 404, request_desc=f"GET /agent-jobs/{job_id} (as other org)", response=cross_tenant,
           message="a different org polling org A's job id must get 404, not 200 or 403")
    story.say("Financial-advice job scenario complete.")
