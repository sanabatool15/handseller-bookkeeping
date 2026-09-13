from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(_wire_fakes):
    with TestClient(app) as c:
        yield c


def register_and_login(client: TestClient, email: str = "owner@example.com") -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Owner", "org_name": "Acme Co"},
        headers={"Idempotency-Key": f"register-{email}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_headers(token: str, idem_key: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key}
