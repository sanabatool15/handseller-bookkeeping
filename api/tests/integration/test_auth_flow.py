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


def test_register_duplicate_email_returns_409(client):
    from tests.integration.conftest import register_and_login

    register_and_login(client, "dup@example.com")
    resp = client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "hunter2pass", "full_name": "X", "org_name": "Other"},
        headers={"Idempotency-Key": "register-dup-2"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already registered"


def test_register_response_shape_unchanged(client):
    from tests.integration.conftest import register_and_login

    body = register_and_login(client, "shape@example.com")
    assert set(body) == {"access_token", "user", "org"}
    assert {"id", "org_id", "email", "full_name", "role"} <= set(body["user"])
    assert {"id", "name", "owner_id"} <= set(body["org"])
