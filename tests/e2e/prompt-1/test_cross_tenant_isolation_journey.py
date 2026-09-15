"""Prompt v1 — Scenario 2: cross-tenant isolation across the full surface.

Two orgs (A and B) each register, log sales/expenses, and trigger an agent
job. Org B must never be able to read/update/delete org A's records by exact
id (always 404, never 403 or 200), and list endpoints must never leak across
orgs. Directly exercises the structural id+org_id scoping guarantee from
`specs/03-multi-tenancy-security.md`, across sales, expenses, AND agent jobs
in one journey (the existing integration tests only cover sales and agent
jobs separately).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from tests.integration.conftest import auth_headers, register_and_login


def test_cross_tenant_isolation_across_sales_expenses_and_agent_jobs(client, monkeypatch):
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))

    org_a = register_and_login(client, email="tenant-a@example.com")
    org_b = register_and_login(client, email="tenant-b@example.com")
    token_a, token_b = org_a["access_token"], org_b["access_token"]

    sale = client.post(
        "/sales",
        json={"amount": 250.0, "category": "retail"},
        headers=auth_headers(token_a, "tenant-a-sale"),
    )
    sale_id = sale.json()["id"]

    expense = client.post(
        "/expenses",
        json={"amount": 40.0, "category": "supplies"},
        headers=auth_headers(token_a, "tenant-a-expense"),
    )
    expense_id = expense.json()["id"]

    job = client.post(
        "/agent-jobs/financial-advice",
        headers=auth_headers(token_a, "tenant-a-job"),
    )
    job_id = job.json()["job_id"]

    # Org B: every direct-by-id access to org A's records is 404.
    assert client.get(f"/sales/{sale_id}", headers=auth_headers(token_b, "unused")).status_code == 404
    assert client.put(
        f"/sales/{sale_id}", json={"amount": 1.0}, headers=auth_headers(token_b, "tenant-b-sale-update")
    ).status_code == 404
    assert client.delete(f"/sales/{sale_id}", headers=auth_headers(token_b, "unused")).status_code == 404

    assert client.get(f"/expenses/{expense_id}", headers=auth_headers(token_b, "unused")).status_code == 404
    assert client.put(
        f"/expenses/{expense_id}", json={"amount": 1.0}, headers=auth_headers(token_b, "tenant-b-expense-update")
    ).status_code == 404
    assert client.delete(f"/expenses/{expense_id}", headers=auth_headers(token_b, "unused")).status_code == 404

    assert client.get(f"/agent-jobs/{job_id}", headers=auth_headers(token_b, "unused")).status_code == 404

    # Org A's own access still works after all the failed cross-tenant attempts.
    assert client.get(f"/sales/{sale_id}", headers=auth_headers(token_a, "unused")).status_code == 200
    assert client.get(f"/expenses/{expense_id}", headers=auth_headers(token_a, "unused")).status_code == 200
    assert client.get(f"/agent-jobs/{job_id}", headers=auth_headers(token_a, "unused")).status_code == 200

    # Org B logs its own data; list endpoints never leak org A's rows into org B's view.
    client.post(
        "/sales", json={"amount": 10.0, "category": "retail"}, headers=auth_headers(token_b, "tenant-b-sale")
    )
    client.post(
        "/expenses", json={"amount": 5.0, "category": "supplies"}, headers=auth_headers(token_b, "tenant-b-expense")
    )

    b_sales = client.get("/sales", headers=auth_headers(token_b, "unused")).json()
    assert sale_id not in {s["id"] for s in b_sales}

    b_expenses = client.get("/expenses", headers=auth_headers(token_b, "unused")).json()
    assert expense_id not in {e["id"] for e in b_expenses}
