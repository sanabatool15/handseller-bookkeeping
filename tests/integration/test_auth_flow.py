from tests.integration.conftest import register_and_login


def test_register_then_login(client):
    reg = register_and_login(client, email="alice@example.com")
    assert "access_token" in reg
    assert reg["org"]["name"] == "Acme Co"

    resp = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "hunter2pass"},
        headers={"Idempotency-Key": "login-1"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_rejected(client):
    register_and_login(client, email="bob@example.com")
    resp = client.post(
        "/auth/login",
        json={"email": "bob@example.com", "password": "wrong"},
        headers={"Idempotency-Key": "login-2"},
    )
    assert resp.status_code == 401


def test_protected_route_requires_auth(client):
    resp = client.get("/sales")
    assert resp.status_code == 401
