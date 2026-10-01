import datetime as dt

from tests.integration.conftest import auth_headers, register_and_login

BODY = {"name": "Mug", "sku": "MUG-1", "price": 12.5, "stock_qty": 4, "reorder_level": 2}


def _iso(v):
    dt.datetime.fromisoformat(v)
    return True


def _two_orgs(client):
    a = register_and_login(client, "pa@example.com")
    b = register_and_login(client, "pb@example.com")
    return a["access_token"], b["access_token"], a


def test_crud_and_json_shape(client):
    tok, _, org = _two_orgs(client)
    r = client.post("/products", json=BODY, headers=auth_headers(tok, "p-create"))
    assert r.status_code == 201, r.text
    p = r.json()
    for k in ("id", "org_id", "created_by"):
        assert isinstance(p[k], str)
    assert p["org_id"] == org["org"]["id"] and p["created_by"] == org["user"]["id"]
    assert p["price"] == 12.5 and isinstance(p["price"], float)
    assert isinstance(p["stock_qty"], int) and isinstance(p["reorder_level"], int) and p["is_active"] is True
    assert _iso(p["created_at"]) and _iso(p["updated_at"])

    assert client.get(f"/products/{p['id']}", headers=auth_headers(tok, "u")).json()["sku"] == "MUG-1"
    assert [x["id"] for x in client.get("/products", headers=auth_headers(tok, "u")).json()] == [p["id"]]
    up = client.put(f"/products/{p['id']}", json={"price": 15, "name": "Big Mug", "is_active": False}, headers=auth_headers(tok, "p-upd"))
    assert up.status_code == 200 and up.json()["price"] == 15 and up.json()["name"] == "Big Mug" and up.json()["is_active"] is False
    assert up.json()["stock_qty"] == 4  # PUT never touches stock
    assert client.delete(f"/products/{p['id']}", headers=auth_headers(tok, "p-del")).status_code == 204
    assert client.get(f"/products/{p['id']}", headers=auth_headers(tok, "u")).status_code == 404


def test_validation_422(client):
    tok, _, _ = _two_orgs(client)
    bad = [{**BODY, "name": ""}, {**BODY, "sku": " "}, {**BODY, "price": -1}, {**BODY, "reorder_level": -1},
           {**BODY, "stock_qty": -1}, {"name": "x"}, {**BODY, "price": "abc"}]
    for i, body in enumerate(bad):
        assert client.post("/products", json=body, headers=auth_headers(tok, f"bad-{i}")).status_code == 422, body
    p = client.post("/products", json=BODY, headers=auth_headers(tok, "ok")).json()
    for i, body in enumerate(({"price": -1}, {"name": ""}, {"reorder_level": -2})):
        assert client.put(f"/products/{p['id']}", json=body, headers=auth_headers(tok, f"badu-{i}")).status_code == 422
    for i, body in enumerate(({"delta": 0}, {"delta": "x"}, {})):
        assert client.post(f"/products/{p['id']}/adjust-stock", json=body, headers=auth_headers(tok, f"bada-{i}")).status_code == 422


def test_duplicate_sku_409_but_other_org_ok(client):
    ta, tb, _ = _two_orgs(client)
    assert client.post("/products", json=BODY, headers=auth_headers(ta, "d1")).status_code == 201
    dup = client.post("/products", json=BODY, headers=auth_headers(ta, "d2"))
    assert dup.status_code == 409 and "MUG-1" in dup.json()["detail"]
    assert client.post("/products", json=BODY, headers=auth_headers(tb, "d3")).status_code == 201
    other = client.post("/products", json={**BODY, "sku": "OTHER"}, headers=auth_headers(ta, "d4")).json()
    clash = client.put(f"/products/{other['id']}", json={"sku": "MUG-1"}, headers=auth_headers(ta, "d5"))
    assert clash.status_code == 409


def test_adjust_stock_success_and_insufficient_409(client):
    tok, _, _ = _two_orgs(client)
    p = client.post("/products", json=BODY, headers=auth_headers(tok, "a1")).json()
    url = f"/products/{p['id']}/adjust-stock"
    up = client.post(url, json={"delta": 6, "reason": "restock"}, headers=auth_headers(tok, "a2"))
    assert up.status_code == 200 and up.json()["stock_qty"] == 10
    ok = client.post(url, json={"delta": -10}, headers=auth_headers(tok, "a3"))
    assert ok.status_code == 200 and ok.json()["stock_qty"] == 0
    bad = client.post(url, json={"delta": -1}, headers=auth_headers(tok, "a4"))
    assert bad.status_code == 409 and "stock" in bad.json()["detail"].lower()
    assert client.get(f"/products/{p['id']}", headers=auth_headers(tok, "u")).json()["stock_qty"] == 0
    assert client.post("/products/nope/adjust-stock", json={"delta": 1}, headers=auth_headers(tok, "a5")).status_code == 404


def test_low_stock_filter(client):
    tok, _, _ = _two_orgs(client)
    client.post("/products", json={**BODY, "sku": "L", "stock_qty": 1, "reorder_level": 2}, headers=auth_headers(tok, "l1"))
    client.post("/products", json={**BODY, "sku": "H", "stock_qty": 50, "reorder_level": 2}, headers=auth_headers(tok, "l2"))
    low = client.get("/products?low_stock=true", headers=auth_headers(tok, "u")).json()
    assert [p["sku"] for p in low] == ["L"]
    assert len(client.get("/products", headers=auth_headers(tok, "u")).json()) == 2


def test_cross_tenant_is_404_never_403(client):
    ta, tb, _ = _two_orgs(client)
    p = client.post("/products", json=BODY, headers=auth_headers(ta, "x1")).json()
    pid = p["id"]
    assert client.get(f"/products/{pid}", headers=auth_headers(tb, "u")).status_code == 404
    assert client.put(f"/products/{pid}", json={"name": "evil"}, headers=auth_headers(tb, "x2")).status_code == 404
    assert client.delete(f"/products/{pid}", headers=auth_headers(tb, "x3")).status_code == 404
    assert client.post(f"/products/{pid}/adjust-stock", json={"delta": -1}, headers=auth_headers(tb, "x4")).status_code == 404
    assert client.post(f"/products/{pid}/adjust-stock", json={"delta": 1}, headers=auth_headers(tb, "x5")).status_code == 404
    assert client.get("/products", headers=auth_headers(tb, "u")).json() == []
    mine = client.get(f"/products/{pid}", headers=auth_headers(ta, "u")).json()
    assert mine["name"] == "Mug" and mine["stock_qty"] == 4


def test_missing_idempotency_key_is_400(client):
    tok, _, _ = _two_orgs(client)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/products", json=BODY, headers=h).status_code == 400
    p = client.post("/products", json=BODY, headers=auth_headers(tok, "k1")).json()
    assert client.put(f"/products/{p['id']}", json={"name": "n"}, headers=h).status_code == 400
    assert client.post(f"/products/{p['id']}/adjust-stock", json={"delta": 1}, headers=h).status_code == 400


def test_idempotent_replay_does_not_double_adjust(client):
    tok, _, _ = _two_orgs(client)
    p = client.post("/products", json=BODY, headers=auth_headers(tok, "r1")).json()
    url = f"/products/{p['id']}/adjust-stock"
    first = client.post(url, json={"delta": 5}, headers=auth_headers(tok, "same"))
    second = client.post(url, json={"delta": 5}, headers=auth_headers(tok, "same"))
    assert first.status_code == second.status_code == 200
    assert client.get(f"/products/{p['id']}", headers=auth_headers(tok, "u")).json()["stock_qty"] == 9
