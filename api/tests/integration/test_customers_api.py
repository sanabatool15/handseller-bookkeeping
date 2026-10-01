import datetime as dt

from tests.integration.conftest import auth_headers, register_and_login

BODY = {"name": "Ana Lopez", "phone": "+49 170 111", "email": "ana@example.com", "address": "Main St 1", "notes": "VIP"}


def _two_orgs(client):
    a = register_and_login(client, "ca@example.com")
    b = register_and_login(client, "cb@example.com")
    return a["access_token"], b["access_token"], a


def _mk(client, tok, key, **over):
    r = client.post("/customers", json={**BODY, **over}, headers=auth_headers(tok, key))
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_and_json_shape(client):
    tok, _, org = _two_orgs(client)
    c = _mk(client, tok, "c-create")
    for k in ("id", "org_id", "created_by"):
        assert isinstance(c[k], str)
    assert c["org_id"] == org["org"]["id"] and c["created_by"] == org["user"]["id"]
    assert c["name"] == "Ana Lopez" and c["phone"] == "+49 170 111" and c["notes"] == "VIP"
    dt.datetime.fromisoformat(c["created_at"])
    dt.datetime.fromisoformat(c["updated_at"])
    assert client.get(f"/customers/{c['id']}", headers=auth_headers(tok, "u")).json()["email"] == "ana@example.com"
    assert [x["id"] for x in client.get("/customers", headers=auth_headers(tok, "u")).json()] == [c["id"]]
    up = client.put(f"/customers/{c['id']}", json={"name": "Ana L.", "phone": None}, headers=auth_headers(tok, "c-upd"))
    assert up.status_code == 200 and up.json()["name"] == "Ana L." and up.json()["phone"] is None and up.json()["email"] == "ana@example.com"
    assert client.delete(f"/customers/{c['id']}", headers=auth_headers(tok, "c-del")).status_code == 204
    assert client.get(f"/customers/{c['id']}", headers=auth_headers(tok, "u")).status_code == 404


def test_validation_422(client):
    tok, _, _ = _two_orgs(client)
    bad = [{"name": ""}, {"name": "  "}, {"phone": "1"}, {"name": "x" * 201}, {"name": "x", "phone": "9" * 33},
           {"name": "x", "email": "nope"}, {"name": "x", "notes": "n" * 1001}, {"name": "x", "address": "a" * 501}]
    for i, body in enumerate(bad):
        assert client.post("/customers", json=body, headers=auth_headers(tok, f"bad-{i}")).status_code == 422, body
    c = _mk(client, tok, "ok")
    for i, body in enumerate(({"name": " "}, {"email": "x"}, {"notes": "n" * 1001})):
        assert client.put(f"/customers/{c['id']}", json=body, headers=auth_headers(tok, f"bu-{i}")).status_code == 422
    assert client.get("/customers?q=" + "x" * 101, headers=auth_headers(tok, "u")).status_code == 422


def test_duplicate_phone_409_but_other_org_and_no_phone_ok(client):
    ta, tb, _ = _two_orgs(client)
    _mk(client, ta, "d1")
    dup = client.post("/customers", json={**BODY, "name": "Other"}, headers=auth_headers(ta, "d2"))
    assert dup.status_code == 409 and "phone" in dup.json()["detail"].lower()
    _mk(client, tb, "d3")  # same phone, other org
    _mk(client, ta, "d4", name="N1", phone=None)
    _mk(client, ta, "d5", name="N2", phone="")  # blank == no phone
    other = _mk(client, ta, "d6", name="Third", phone="777")
    assert client.put(f"/customers/{other['id']}", json={"phone": BODY["phone"]}, headers=auth_headers(ta, "d7")).status_code == 409


def test_search_q_prefix_and_wildcards_literal(client):
    tok, _, _ = _two_orgs(client)
    for i, (n, ph) in enumerate((("Anna", "100"), ("Annabel", None), ("Bob", "1%0"), ("a_b", None), ("axb", None))):
        _mk(client, tok, f"s{i}", name=n, phone=ph)
    names = lambda q: [c["name"] for c in client.get("/customers", params={"q": q}, headers=auth_headers(tok, "u")).json()]  # noqa: E731
    assert names("ann") == ["Anna", "Annabel"]
    assert names("10") == ["Anna"]           # phone prefix
    assert names("1%") == ["Bob"]            # LIKE wildcard treated literally
    assert names("%") == [] and names("_") == []
    assert names("a_") == ["a_b"]
    assert names("zzz") == []
    assert len(client.get("/customers?q=", headers=auth_headers(tok, "u")).json()) == 5


def test_list_paging(client):
    tok, _, _ = _two_orgs(client)
    for i, n in enumerate("ABC"):
        _mk(client, tok, f"p{i}", name=n, phone=None)
    got = client.get("/customers?limit=1&offset=1", headers=auth_headers(tok, "u")).json()
    assert [c["name"] for c in got] == ["B"]


def test_sales_link_summary_and_delete_409(client):
    tok, _, _ = _two_orgs(client)
    c = _mk(client, tok, "l1")
    s = client.post("/sales", json={"amount": 10, "customer_id": c["id"], "customer_name": "Ana (walk-in)"}, headers=auth_headers(tok, "l2"))
    assert s.status_code == 201 and s.json()["customer_id"] == c["id"] and s.json()["customer_name"] == "Ana (walk-in)"
    s2 = client.post("/sales", json={"amount": 5.5, "customer_id": c["id"]}, headers=auth_headers(tok, "l3")).json()
    plain = client.post("/sales", json={"amount": 99}, headers=auth_headers(tok, "l4"))
    assert plain.status_code == 201 and plain.json()["customer_id"] is None  # old behaviour, null link
    assert client.get(f"/sales/{s.json()['id']}", headers=auth_headers(tok, "u")).json()["customer_id"] == c["id"]

    sm = client.get(f"/customers/{c['id']}/summary", headers=auth_headers(tok, "u")).json()
    assert sm["total_sales"] == 15.5 and sm["sale_count"] == 2 and dt.date.fromisoformat(sm["last_sale_date"])
    assert sm["customer"]["id"] == c["id"] and set(sm) == {"customer", "total_sales", "sale_count", "last_sale_date"}

    assert client.delete(f"/customers/{c['id']}", headers=auth_headers(tok, "l5")).status_code == 409
    assert client.get(f"/customers/{c['id']}", headers=auth_headers(tok, "u")).status_code == 200
    # unlink via PUT null, then the delete succeeds
    for key, sid in (("l6", s.json()["id"]), ("l7", s2["id"])):
        up = client.put(f"/sales/{sid}", json={"customer_id": None}, headers=auth_headers(tok, key))
        assert up.status_code == 200 and up.json()["customer_id"] is None
    assert client.get(f"/customers/{c['id']}/summary", headers=auth_headers(tok, "u")).json()["sale_count"] == 0
    assert client.delete(f"/customers/{c['id']}", headers=auth_headers(tok, "l8")).status_code == 204


def test_sale_put_without_customer_id_keeps_link(client):
    tok, _, _ = _two_orgs(client)
    c = _mk(client, tok, "k1")
    s = client.post("/sales", json={"amount": 1, "customer_id": c["id"]}, headers=auth_headers(tok, "k2")).json()
    up = client.put(f"/sales/{s['id']}", json={"amount": 2}, headers=auth_headers(tok, "k3"))
    assert up.json()["amount"] == 2 and up.json()["customer_id"] == c["id"]


def test_summary_of_empty_customer(client):
    tok, _, _ = _two_orgs(client)
    c = _mk(client, tok, "e1")
    sm = client.get(f"/customers/{c['id']}/summary", headers=auth_headers(tok, "u")).json()
    assert sm["total_sales"] == 0 and sm["sale_count"] == 0 and sm["last_sale_date"] is None


def test_cross_tenant_is_404_never_403(client):
    ta, tb, _ = _two_orgs(client)
    c = _mk(client, ta, "x1")
    cid = c["id"]
    assert client.get(f"/customers/{cid}", headers=auth_headers(tb, "u")).status_code == 404
    assert client.get(f"/customers/{cid}/summary", headers=auth_headers(tb, "u")).status_code == 404
    assert client.put(f"/customers/{cid}", json={"name": "evil"}, headers=auth_headers(tb, "x2")).status_code == 404
    assert client.delete(f"/customers/{cid}", headers=auth_headers(tb, "x3")).status_code == 404
    assert client.get("/customers", headers=auth_headers(tb, "u")).json() == []
    assert client.get("/customers?q=Ana", headers=auth_headers(tb, "u")).json() == []
    assert client.get(f"/customers/{cid}", headers=auth_headers(ta, "u")).json()["name"] == "Ana Lopez"
    # even a customer with sales answers 404 (not 409) to the other org's delete
    client.post("/sales", json={"amount": 1, "customer_id": cid}, headers=auth_headers(ta, "x4"))
    assert client.delete(f"/customers/{cid}", headers=auth_headers(tb, "x5")).status_code == 404
    assert client.get(f"/customers/{cid}/summary", headers=auth_headers(ta, "u")).json()["sale_count"] == 1


def test_sale_with_foreign_or_unknown_customer_is_404(client):
    ta, tb, _ = _two_orgs(client)
    foreign = _mk(client, ta, "f1")
    r = client.post("/sales", json={"amount": 5, "customer_id": foreign["id"]}, headers=auth_headers(tb, "f2"))
    unknown = client.post("/sales", json={"amount": 5, "customer_id": "00000000-0000-0000-0000-000000000000"}, headers=auth_headers(tb, "f3"))
    assert r.status_code == 404 and r.json() == unknown.json() and r.json()["detail"] == "Customer not found"
    assert client.get("/sales", headers=auth_headers(tb, "u")).json() == []  # nothing was created
    mine = client.post("/sales", json={"amount": 5}, headers=auth_headers(tb, "f4")).json()
    up = client.put(f"/sales/{mine['id']}", json={"customer_id": foreign["id"]}, headers=auth_headers(tb, "f5"))
    assert up.status_code == 404 and up.json()["detail"] == "Customer not found"
    assert client.get(f"/sales/{mine['id']}", headers=auth_headers(tb, "u")).json()["customer_id"] is None


def test_missing_idempotency_key_and_replay(client):
    tok, _, _ = _two_orgs(client)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/customers", json=BODY, headers=h).status_code == 400
    c = _mk(client, tok, "i1")
    assert client.put(f"/customers/{c['id']}", json={"name": "n"}, headers=h).status_code == 400
    first = client.post("/customers", json={"name": "Rep", "phone": None}, headers=auth_headers(tok, "same"))
    second = client.post("/customers", json={"name": "Rep", "phone": None}, headers=auth_headers(tok, "same"))
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert len(client.get("/customers?q=Rep", headers=auth_headers(tok, "u")).json()) == 1
