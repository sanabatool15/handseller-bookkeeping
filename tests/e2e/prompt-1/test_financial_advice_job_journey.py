"""Prompt v1 — Scenario 4: financial-advice background job lifecycle.

A user logs sales/expenses, triggers the job (must return 202 immediately,
never blocking on the LLM call per `specs/05-background-jobs-inngest.md`),
then the test drives the job's own step functions in-process — standing in
for the live Inngest dev server used by the separately-gated
`tests/e2e/test_full_inngest_workflow.py` — and polls the status endpoint
until completion. Also confirms cross-tenant 404 on job status.

This does not require RUN_E2E / a live docker-compose stack: it exercises
the real HTTP trigger/poll contract plus the real job step logic
(`jobs/financial_agent_job.py`), just without a live Inngest event bus
driving the invocation, consistent with `_wire_fakes` (no live infra).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from tests.integration.conftest import auth_headers, register_and_login


def test_financial_advice_job_returns_202_then_completes_with_advice(client, monkeypatch):
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))

    org = register_and_login(client, email="advisee@example.com")
    token = org["access_token"]

    client.post("/sales", json={"amount": 400.0, "category": "retail"}, headers=auth_headers(token, "fa-sale"))
    client.post("/expenses", json={"amount": 50.0, "category": "supplies"}, headers=auth_headers(token, "fa-expense"))

    trigger = client.post("/agent-jobs/financial-advice", headers=auth_headers(token, "fa-trigger"))
    assert trigger.status_code == 202
    body = trigger.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]

    # Not yet completed until the worker (simulated below) runs the steps.
    pending_status = client.get(f"/agent-jobs/{job_id}", headers=auth_headers(token, "unused"))
    assert pending_status.status_code == 200
    assert pending_status.json()["status"] in ("pending", "processing")

    # Drive the real job step functions directly, standing in for the
    # Inngest worker actually invoking `financial_advisor_job`.
    from jobs.financial_agent_job import _step_gather_data, _step_run_agent, _step_finalize

    async def run_job_steps() -> dict:
        summary = await _step_gather_data(job_id, org["org"]["id"])
        result = await _step_run_agent(job_id, org["org"]["id"], summary)
        return await _step_finalize(job_id, org["org"]["id"], result)

    asyncio.run(run_job_steps())

    completed_status = client.get(f"/agent-jobs/{job_id}", headers=auth_headers(token, "unused"))
    assert completed_status.status_code == 200
    completed_body = completed_status.json()
    assert completed_body["status"] == "completed"
    assert completed_body["result"] is not None
    # Per specs/05: falls back to rule-based advice whenever the SDK path
    # fails/is unreachable; assert either is acceptable rather than pinning
    # to the fallback (see SCENARIOS.md "Assumptions and gaps").
    assert completed_body["result"]["source"] in ("openai_agent", "rule_based_fallback")
    assert "advice" in completed_body["result"]


def test_agent_job_status_not_visible_to_other_org(client, monkeypatch):
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))

    org_a = register_and_login(client, email="job-owner-a@example.com")
    org_b = register_and_login(client, email="job-owner-b@example.com")

    trigger = client.post(
        "/agent-jobs/financial-advice", headers=auth_headers(org_a["access_token"], "fa-cross-tenant")
    )
    job_id = trigger.json()["job_id"]

    cross = client.get(f"/agent-jobs/{job_id}", headers=auth_headers(org_b["access_token"], "unused"))
    assert cross.status_code == 404
