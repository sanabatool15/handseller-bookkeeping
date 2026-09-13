from unittest.mock import AsyncMock

from tests.integration.conftest import auth_headers, register_and_login


def test_request_financial_advice_returns_202_with_job_id(client, monkeypatch):
    # Never make a real network call to an Inngest dev server in tests.
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))

    org = register_and_login(client, email="jobowner@example.com")
    resp = client.post(
        "/agent-jobs/financial-advice",
        headers=auth_headers(org["access_token"], "job-1"),
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert "job_id" in body

    status_resp = client.get(f"/agent-jobs/{body['job_id']}", headers=auth_headers(org["access_token"], "unused"))
    assert status_resp.status_code == 200
    assert status_resp.json()["job_name"] == "financial_advisor"


def test_job_status_not_visible_to_other_org(client, monkeypatch):
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))

    org_a = register_and_login(client, email="joba@example.com")
    org_b = register_and_login(client, email="jobb@example.com")

    resp = client.post("/agent-jobs/financial-advice", headers=auth_headers(org_a["access_token"], "job-a"))
    job_id = resp.json()["job_id"]

    cross_tenant = client.get(f"/agent-jobs/{job_id}", headers=auth_headers(org_b["access_token"], "unused"))
    assert cross_tenant.status_code == 404
