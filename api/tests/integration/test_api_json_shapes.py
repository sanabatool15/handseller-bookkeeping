"""The JSON the frontend (lib/types.ts) consumes: amounts are numbers, dates ISO strings, ids strings.
Guards the SQL Server port against type drift (Decimal/date/uniqueidentifier must be normalised)."""
from __future__ import annotations

import datetime as dt
import re
from unittest.mock import AsyncMock

from tests.integration.conftest import auth_headers, register_and_login

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_iso_datetime(v) -> bool:
    try:
        dt.datetime.fromisoformat(v)
        return isinstance(v, str)
    except (TypeError, ValueError):
        return False


def _check_ledger_entry(row: dict, *, date_field: str, other_keys: set[str]):
    assert {"id", "org_id", "created_by", "amount", "category", "description", date_field, "created_at", "updated_at"} | other_keys <= set(row)
    for k in ("id", "org_id", "created_by"):
        assert isinstance(row[k], str)
    assert isinstance(row["amount"], (int, float)) and not isinstance(row["amount"], bool)
    assert isinstance(row["category"], str)
    assert isinstance(row[date_field], str) and ISO_DATE.match(row[date_field])
    assert _is_iso_datetime(row["created_at"]) and _is_iso_datetime(row["updated_at"])


def test_sales_shape(client):
    org = register_and_login(client, "shape-sales@example.com")
    h = lambda k: auth_headers(org["access_token"], k)  # noqa: E731
    created = client.post("/sales", json={"amount": 19.99, "category": "retail", "customer_name": "Zed"}, headers=h("s1"))
    assert created.status_code == 201
    _check_ledger_entry(created.json(), date_field="sale_date", other_keys={"customer_name"})
    assert created.json()["created_by"] == org["user"]["id"] and created.json()["amount"] == 19.99

    listing = client.get("/sales", headers=h("u")).json()
    assert isinstance(listing, list) and len(listing) == 1
    _check_ledger_entry(listing[0], date_field="sale_date", other_keys={"customer_name"})
    one = client.get(f"/sales/{created.json()['id']}", headers=h("u")).json()
    _check_ledger_entry(one, date_field="sale_date", other_keys={"customer_name"})
    updated = client.put(f"/sales/{one['id']}", json={"amount": 20.5}, headers=h("s2")).json()
    _check_ledger_entry(updated, date_field="sale_date", other_keys={"customer_name"})
    assert updated["amount"] == 20.5


def test_expenses_shape(client):
    org = register_and_login(client, "shape-exp@example.com")
    h = lambda k: auth_headers(org["access_token"], k)  # noqa: E731
    created = client.post("/expenses", json={"amount": 5.25, "category": "rent", "voucher_reference": "V-7"}, headers=h("x1"))
    assert created.status_code == 201
    _check_ledger_entry(created.json(), date_field="expense_date", other_keys={"voucher_reference"})
    assert created.json()["voucher_reference"] == "V-7"
    listing = client.get("/expenses", headers=h("u")).json()
    _check_ledger_entry(listing[0], date_field="expense_date", other_keys={"voucher_reference"})


def test_agent_job_shape(client, monkeypatch):
    from jobs import inngest_client as inngest_client_module

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", AsyncMock(return_value=None))
    org = register_and_login(client, "shape-job@example.com")
    h = lambda k: auth_headers(org["access_token"], k)  # noqa: E731
    accepted = client.post("/agent-jobs/financial-advice", json={"question": "How are we doing?"}, headers=h("j1"))
    assert accepted.status_code == 202
    body = accepted.json()
    assert set(body) == {"job_id", "status", "message"} and isinstance(body["job_id"], str) and body["status"] == "pending"

    job = client.get(f"/agent-jobs/{body['job_id']}", headers=h("u")).json()
    assert {"id", "job_name", "org_id", "requested_by", "status", "current_step", "input_payload", "result",
            "error_details", "created_at", "updated_at"} <= set(job)
    assert isinstance(job["id"], str) and isinstance(job["org_id"], str) and job["requested_by"] == org["user"]["id"]
    assert job["status"] in {"pending", "processing", "completed", "failed"}
    assert job["input_payload"] == {"question": "How are we doing?"}  # dict, not a JSON string
    assert job["result"] is None and job["current_step"] is None
    assert _is_iso_datetime(job["created_at"]) and _is_iso_datetime(job["updated_at"])


def test_auth_shapes(client):
    reg = register_and_login(client, "shape-auth@example.com")
    for k in ("id", "org_id", "email"):
        assert isinstance(reg["user"][k], str)
    assert isinstance(reg["org"]["id"], str) and isinstance(reg["org"]["name"], str)
    login = client.post("/auth/login", json={"email": "shape-auth@example.com", "password": "hunter2pass"}, headers={"Idempotency-Key": "l1"})
    assert login.status_code == 200
    assert set(login.json()) == {"access_token", "user"} and login.json()["user"]["org_id"] == reg["org"]["id"]


def test_health_reports_database_check(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["checks"]["database"] == "ok" and "supabase" not in body["checks"]
