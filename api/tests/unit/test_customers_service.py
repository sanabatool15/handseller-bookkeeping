import pytest

from services import customers_service as svc
from services import sales_service


def _mk(db, org="org-1", name="Ana", **kw):
    return svc.create_customer(db, org_id=org, user_id="u1", name=name, **kw)


def test_create_trims_and_blank_optionals_become_none(fake_db):
    c = _mk(fake_db, name="  Ana  ", phone="  ", email="", address=None, notes=" n ")
    assert c["name"] == "Ana" and c["phone"] is None and c["email"] is None and c["notes"] == "n" and c["org_id"] == "org-1"


@pytest.mark.parametrize("kw", [
    {"name": ""}, {"name": "  "}, {"name": "x" * 201}, {"phone": "1" * 33}, {"email": "a" * 321}, {"email": "no-at"},
    {"email": "a b@c.d"}, {"address": "x" * 501}, {"notes": "x" * 1001},
])
def test_create_validation(fake_db, kw):
    with pytest.raises(svc.ValidationError):
        _mk(fake_db, **kw)


def test_phone_unique_per_org_but_many_without_phone(fake_db):
    _mk(fake_db, phone="555")
    with pytest.raises(svc.DuplicatePhoneError):
        _mk(fake_db, name="Bob", phone="555")
    _mk(fake_db, org="org-2", phone="555")  # other org ok
    _mk(fake_db, name="N1")
    _mk(fake_db, name="N2")  # several customers without a phone (filtered index ignores NULL)


def test_get_update_delete_summary_org_scoped(fake_db):
    c = _mk(fake_db)
    for call in (
        lambda: svc.get_customer(fake_db, org_id="org-2", customer_id=c["id"]),
        lambda: svc.update_customer(fake_db, org_id="org-2", customer_id=c["id"], updates={"name": "evil"}),
        lambda: svc.delete_customer(fake_db, org_id="org-2", customer_id=c["id"]),
        lambda: svc.get_customer_summary(fake_db, org_id="org-2", customer_id=c["id"]),
    ):
        with pytest.raises(svc.NotFoundError):
            call()
    assert svc.get_customer(fake_db, org_id="org-1", customer_id=c["id"])["name"] == "Ana"


def test_update_semantics_clear_and_keep(fake_db):
    c = _mk(fake_db, phone="1", email="a@b.c", notes="x")
    u = svc.update_customer(fake_db, org_id="org-1", customer_id=c["id"], updates={"name": None, "phone": None, "notes": " y "})
    assert u["name"] == "Ana" and u["phone"] is None and u["notes"] == "y" and u["email"] == "a@b.c"
    with pytest.raises(svc.ValidationError):
        svc.update_customer(fake_db, org_id="org-1", customer_id=c["id"], updates={"name": " "})


def test_update_duplicate_phone(fake_db):
    _mk(fake_db, phone="1")
    b = _mk(fake_db, name="B", phone="2")
    with pytest.raises(svc.DuplicatePhoneError):
        svc.update_customer(fake_db, org_id="org-1", customer_id=b["id"], updates={"phone": "1"})
    assert svc.update_customer(fake_db, org_id="org-1", customer_id=b["id"], updates={"phone": "2"})["phone"] == "2"


def test_search_prefix_literal_wildcards_and_paging(fake_db):
    for n, ph in (("Anna", "100"), ("Annabel", None), ("Bob", "1%0"), ("50% Off Shop", None), ("a_b", None), ("axb", None)):
        _mk(fake_db, name=n, phone=ph)
    _mk(fake_db, org="org-2", name="Anna")
    names = lambda **k: [c["name"] for c in svc.list_customers(fake_db, org_id="org-1", **k)]  # noqa: E731
    assert names(q="ann") == ["Anna", "Annabel"]
    assert names(q="1%") == ["Bob"]            # '%' is literal, not "match anything"
    assert names(q="a_") == ["a_b"]            # '_' literal: does not match "axb"
    assert names(q="%") == []                  # literal prefix: no name starts with '%'
    assert names(q="50%") == ["50% Off Shop"]
    assert names(q="100") == ["Anna"]          # phone prefix
    assert names(limit=2, offset=1) == ["a_b", "Anna"]  # 50% Off Shop, a_b, Anna, Annabel, axb, Bob
    with pytest.raises(svc.ValidationError):
        svc.list_customers(fake_db, org_id="org-1", q="x" * 101)


def test_summary_and_delete_blocked_by_sales(fake_db):
    c = _mk(fake_db)
    empty = svc.get_customer_summary(fake_db, org_id="org-1", customer_id=c["id"])
    assert empty["total_sales"] == 0 and empty["sale_count"] == 0 and empty["last_sale_date"] is None
    sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=10, category="g", customer_id=c["id"])
    s2 = sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=5.5, category="g", customer_id=c["id"])
    sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=99, category="g")  # not this customer
    sm = svc.get_customer_summary(fake_db, org_id="org-1", customer_id=c["id"])
    assert sm["total_sales"] == 15.5 and sm["sale_count"] == 2 and sm["last_sale_date"] and sm["customer"]["id"] == c["id"]
    with pytest.raises(svc.CustomerInUseError):
        svc.delete_customer(fake_db, org_id="org-1", customer_id=c["id"])
    sales_service.update_sale(fake_db, org_id="org-1", sale_id=s2["id"], updates={"customer_id": None})  # unlink
    assert svc.get_customer_summary(fake_db, org_id="org-1", customer_id=c["id"])["sale_count"] == 1
    with pytest.raises(svc.NotFoundError):
        svc.delete_customer(fake_db, org_id="org-2", customer_id=c["id"])  # other org: 404, not 409


def test_delete_without_sales(fake_db):
    c = _mk(fake_db)
    svc.delete_customer(fake_db, org_id="org-1", customer_id=c["id"])
    with pytest.raises(svc.NotFoundError):
        svc.delete_customer(fake_db, org_id="org-1", customer_id=c["id"])


def test_sale_customer_must_belong_to_org(fake_db):
    mine, theirs = _mk(fake_db), _mk(fake_db, org="org-2", name="T")
    s = sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=1, category="g", customer_id=mine["id"])
    assert s["customer_id"] == mine["id"]
    assert sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=1, category="g")["customer_id"] is None
    for cid in (theirs["id"], "no-such-customer"):
        with pytest.raises(sales_service.NotFoundError, match="Customer not found"):
            sales_service.create_sale(fake_db, org_id="org-1", user_id="u", amount=1, category="g", customer_id=cid)
        with pytest.raises(sales_service.NotFoundError, match="Customer not found"):
            sales_service.update_sale(fake_db, org_id="org-1", sale_id=s["id"], updates={"customer_id": cid})
    assert sales_service.update_sale(fake_db, org_id="org-1", sale_id=s["id"], updates={"amount": 3})["customer_id"] == mine["id"]
