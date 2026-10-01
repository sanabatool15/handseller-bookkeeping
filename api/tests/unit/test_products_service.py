import pytest

from services import products_service as svc


def _mk(db, org="org-1", sku="SKU-1", **kw):
    args = dict(name="Mug", sku=sku, price=9.5, stock_qty=5, reorder_level=2)
    args.update(kw)
    return svc.create_product(db, org_id=org, user_id="u1", **args)


def test_create_success_and_defaults(fake_db):
    p = _mk(fake_db)
    assert p["org_id"] == "org-1" and p["sku"] == "SKU-1" and p["stock_qty"] == 5 and p["is_active"] is True
    d = svc.create_product(fake_db, org_id="org-1", user_id="u1", name="x", sku="S2", price=0)
    assert d["stock_qty"] == 0 and d["reorder_level"] == 0 and d["price"] == 0


@pytest.mark.parametrize("kw", [
    {"name": ""}, {"name": "   "}, {"sku": ""}, {"sku": "  "}, {"price": -0.01},
    {"reorder_level": -1}, {"stock_qty": -1}, {"name": "x" * 201}, {"sku": "x" * 65}, {"stock_qty": 10**9},
])
def test_create_validation(fake_db, kw):
    with pytest.raises(svc.ValidationError):
        _mk(fake_db, **kw)


def test_duplicate_sku_same_org_only(fake_db):
    _mk(fake_db)
    with pytest.raises(svc.DuplicateSkuError):
        _mk(fake_db, name="Other")
    _mk(fake_db, org="org-2")  # same SKU in another org is fine


def test_get_update_delete_are_org_scoped(fake_db):
    p = _mk(fake_db)
    assert svc.get_product(fake_db, org_id="org-1", product_id=p["id"])["id"] == p["id"]
    with pytest.raises(svc.NotFoundError):
        svc.get_product(fake_db, org_id="org-2", product_id=p["id"])
    with pytest.raises(svc.NotFoundError):
        svc.update_product(fake_db, org_id="org-2", product_id=p["id"], updates={"name": "evil"})
    with pytest.raises(svc.NotFoundError):
        svc.delete_product(fake_db, org_id="org-2", product_id=p["id"])
    with pytest.raises(svc.NotFoundError):
        svc.adjust_stock(fake_db, org_id="org-2", product_id=p["id"], delta=1)
    assert svc.get_product(fake_db, org_id="org-1", product_id=p["id"])["name"] == "Mug"
    assert svc.get_product(fake_db, org_id="org-1", product_id=p["id"])["stock_qty"] == 5


def test_update_validation_and_none_stripped(fake_db):
    p = _mk(fake_db)
    u = svc.update_product(fake_db, org_id="org-1", product_id=p["id"], updates={"name": " New ", "price": None, "is_active": False})
    assert u["name"] == "New" and u["price"] == 9.5 and u["is_active"] is False
    for bad in ({"name": " "}, {"sku": ""}, {"price": -1}, {"reorder_level": -3}):
        with pytest.raises(svc.ValidationError):
            svc.update_product(fake_db, org_id="org-1", product_id=p["id"], updates=bad)


def test_update_duplicate_sku(fake_db):
    _mk(fake_db, sku="A")
    b = _mk(fake_db, sku="B")
    with pytest.raises(svc.DuplicateSkuError):
        svc.update_product(fake_db, org_id="org-1", product_id=b["id"], updates={"sku": "A"})
    assert svc.update_product(fake_db, org_id="org-1", product_id=b["id"], updates={"sku": "B"})["sku"] == "B"  # own sku ok


def test_delete(fake_db):
    p = _mk(fake_db)
    svc.delete_product(fake_db, org_id="org-1", product_id=p["id"])
    with pytest.raises(svc.NotFoundError):
        svc.delete_product(fake_db, org_id="org-1", product_id=p["id"])


def test_adjust_stock_success_insufficient_notfound(fake_db):
    p = _mk(fake_db, stock_qty=5)
    assert svc.adjust_stock(fake_db, org_id="org-1", product_id=p["id"], delta=3, reason="restock")["stock_qty"] == 8
    assert svc.adjust_stock(fake_db, org_id="org-1", product_id=p["id"], delta=-8)["stock_qty"] == 0  # exactly to zero ok
    with pytest.raises(svc.InsufficientStockError):
        svc.adjust_stock(fake_db, org_id="org-1", product_id=p["id"], delta=-1)
    assert svc.get_product(fake_db, org_id="org-1", product_id=p["id"])["stock_qty"] == 0
    with pytest.raises(svc.NotFoundError):
        svc.adjust_stock(fake_db, org_id="org-1", product_id="missing", delta=1)


@pytest.mark.parametrize("delta,reason", [(0, None), (10**7, None), (-10**7, None), (1, "r" * 501)])
def test_adjust_validation(fake_db, delta, reason):
    p = _mk(fake_db)
    with pytest.raises(svc.ValidationError):
        svc.adjust_stock(fake_db, org_id="org-1", product_id=p["id"], delta=delta, reason=reason)


def test_list_low_stock_and_paging(fake_db):
    _mk(fake_db, sku="A", name="A", stock_qty=1, reorder_level=2)
    _mk(fake_db, sku="B", name="B", stock_qty=2, reorder_level=2)   # boundary: <= reorder_level is low
    _mk(fake_db, sku="C", name="C", stock_qty=3, reorder_level=2)
    _mk(fake_db, org="org-2", sku="D", name="D", stock_qty=0)
    assert [p["sku"] for p in svc.list_products(fake_db, org_id="org-1")] == ["A", "B", "C"]
    assert [p["sku"] for p in svc.list_products(fake_db, org_id="org-1", low_stock=True)] == ["A", "B"]
    assert [p["sku"] for p in svc.list_products(fake_db, org_id="org-1", limit=1, offset=1)] == ["B"]
