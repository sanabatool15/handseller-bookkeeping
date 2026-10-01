"""Sale line items + cash ledger through the service, with the in-memory fakes that mirror usp_RecordSale/usp_VoidSale."""
import uuid

import pytest

from core.db import is_deadlock
from repository import sales_repository
from services import cash_service, products_service, sales_service

ORG, OTHER = "org-1", "org-2"


def _product(db, org=ORG, sku="MUG", stock=5, price=10.0, name="Mug"):
    return products_service.create_product(db, org_id=org, user_id="u1", name=name, sku=sku, price=price, stock_qty=stock)


def _stock(db, pid, org=ORG):
    return products_service.get_product(db, org_id=org, product_id=pid)["stock_qty"]


def _balance(db, org=ORG):
    return cash_service.get_balance(db, org_id=org)["balance"]


def _sell(db, items, org=ORG, **kw):
    return sales_service.create_sale(db, org_id=org, user_id="u1", category="retail", items=items, **kw)


def test_commit_with_items_reduces_stock_and_increases_balance(fake_db):
    mug, pen = _product(fake_db), _product(fake_db, sku="PEN", price=2.5, name="Pen", stock=10)
    sale = _sell(fake_db, [{"product_id": mug["id"], "quantity": 2}, {"product_id": pen["id"], "quantity": 4, "unit_price": 3}])
    assert sale["amount"] == 32.0  # 2*10 (price defaults to the product's) + 4*3 (explicit)
    assert [i["line_total"] for i in sorted(sale["items"], key=lambda i: i["quantity"])] == [20.0, 12.0]
    assert {i["product_name"] for i in sale["items"]} == {"Mug", "Pen"}
    assert _stock(fake_db, mug["id"]) == 3 and _stock(fake_db, pen["id"]) == 6
    assert _balance(fake_db) == 32.0
    ledger = cash_service.list_ledger(fake_db, org_id=ORG)
    assert len(ledger) == 1 and ledger[0]["entry_type"] == "sale" and ledger[0]["amount"] == 32.0
    assert ledger[0]["balance_after"] == 32.0 and ledger[0]["ref_id"] == sale["id"]


def test_insufficient_stock_rolls_back_everything(fake_db):
    ok, scarce = _product(fake_db), _product(fake_db, sku="PEN", name="Pen", stock=1)
    with pytest.raises(sales_service.InsufficientStockError, match="Not enough stock for Pen"):
        _sell(fake_db, [{"product_id": ok["id"], "quantity": 2}, {"product_id": scarce["id"], "quantity": 2}])
    assert _stock(fake_db, ok["id"]) == 5 and _stock(fake_db, scarce["id"]) == 1  # first item NOT kept
    assert sales_service.list_sales(fake_db, org_id=ORG) == []
    assert _balance(fake_db) == 0.0 and cash_service.list_ledger(fake_db, org_id=ORG) == []


def test_skip_invalid_items_keeps_valid_ones(fake_db):
    ok, scarce = _product(fake_db), _product(fake_db, sku="PEN", name="Pen", stock=1)
    ghost = str(uuid.uuid4())
    sale = _sell(fake_db, [{"product_id": ok["id"], "quantity": 1}, {"product_id": scarce["id"], "quantity": 9},
                           {"product_id": ghost, "quantity": 1}], skip_invalid_items=True)
    assert [i["product_id"] for i in sale["items"]] == [ok["id"]] and sale["amount"] == 10.0
    assert sorted(s["error_number"] for s in sale["skipped_items"]) == [50001, 50002]
    assert _stock(fake_db, ok["id"]) == 4 and _stock(fake_db, scarce["id"]) == 1
    assert _balance(fake_db) == 10.0


def test_skip_with_no_valid_item_is_rolled_back(fake_db):
    scarce = _product(fake_db, stock=0)
    with pytest.raises(sales_service.InsufficientStockError):
        _sell(fake_db, [{"product_id": scarce["id"], "quantity": 1}], skip_invalid_items=True)
    assert sales_service.list_sales(fake_db, org_id=ORG) == [] and _balance(fake_db) == 0.0


def test_stock_never_negative_and_balance_equals_sum_of_sales(fake_db):
    p = _product(fake_db, stock=3)
    committed = 0.0
    for _ in range(6):
        try:
            committed += _sell(fake_db, [{"product_id": p["id"], "quantity": 1}])["amount"]
        except sales_service.InsufficientStockError:
            pass
    assert _stock(fake_db, p["id"]) == 0 and committed == 30.0 and _balance(fake_db) == committed
    ledger = cash_service.list_ledger(fake_db, org_id=ORG)
    assert sum(e["amount"] for e in ledger) == _balance(fake_db)


def test_foreign_or_unknown_product_is_404_and_changes_nothing(fake_db):
    foreign = _product(fake_db, org=OTHER, sku="X")
    with pytest.raises(sales_service.NotFoundError, match="Product not found"):
        _sell(fake_db, [{"product_id": foreign["id"], "quantity": 1}])
    with pytest.raises(sales_service.NotFoundError, match="Product not found"):
        _sell(fake_db, [{"product_id": str(uuid.uuid4()), "quantity": 1}])
    assert _stock(fake_db, foreign["id"], org=OTHER) == 5 and _balance(fake_db, OTHER) == 0.0


def test_plain_sale_back_compat_posts_cash_and_has_empty_items(fake_db):
    sale = sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=40.0, category="retail")
    assert sale["items"] == [] and sale["amount"] == 40.0 and "skipped_items" not in sale
    assert _balance(fake_db) == 40.0


@pytest.mark.parametrize("kw", [
    {}, {"amount": 0}, {"amount": -1}, {"items": [{"product_id": "nope", "quantity": 1}]},
    {"items": [{"product_id": str(uuid.uuid4()), "quantity": 0}]}, {"items": [{"product_id": str(uuid.uuid4()), "quantity": 1.5}]},
    {"items": [{"product_id": str(uuid.uuid4()), "quantity": 1, "unit_price": -1}]},
])
def test_validation(fake_db, kw):
    with pytest.raises(sales_service.ValidationError):
        sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", category="x", **kw)


def test_void_restores_stock_and_balance_and_is_scoped(fake_db):
    p = _product(fake_db)
    sale = _sell(fake_db, [{"product_id": p["id"], "quantity": 3}])
    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(fake_db, org_id=OTHER, sale_id=sale["id"])  # foreign => 404, nothing changed
    assert _stock(fake_db, p["id"]) == 2 and _balance(fake_db) == 30.0
    sales_service.delete_sale(fake_db, org_id=ORG, sale_id=sale["id"], user_id="u1")
    assert _stock(fake_db, p["id"]) == 5 and _balance(fake_db) == 0.0
    assert [e["entry_type"] for e in cash_service.list_ledger(fake_db, org_id=ORG)] == ["sale_void", "sale"]
    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(fake_db, org_id=ORG, sale_id=sale["id"])  # already gone


def test_update_amount_rejected_for_item_sales_but_metadata_ok(fake_db):
    p = _product(fake_db)
    sale = _sell(fake_db, [{"product_id": p["id"], "quantity": 1}])
    with pytest.raises(sales_service.ValidationError):
        sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 1})
    upd = sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"category": "gift"})
    assert upd["category"] == "gift" and upd["amount"] == 10.0 and len(upd["items"]) == 1
    with pytest.raises(sales_service.NotFoundError):
        sales_service.update_sale(fake_db, org_id=OTHER, sale_id=sale["id"], updates={"amount": 1})


def test_foreign_customer_is_404(fake_db):
    with pytest.raises(sales_service.NotFoundError, match="Customer"):
        sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=5, category="x", customer_id=str(uuid.uuid4()))


def test_deadlock_victim_is_retried_once_and_reported(fake_db, monkeypatch):
    real = sales_repository.record_sale
    calls = {"n": 0}

    def flaky(db, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sales_repository.ProcedureError(1205, "Transaction was deadlocked ... chosen as the deadlock victim")
        return real(db, **kw)

    monkeypatch.setattr(sales_repository, "record_sale", flaky)
    events = []
    sale = sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=7, category="x",
                                     on_event=lambda step, **info: events.append((step, info["attempt"])))
    assert calls["n"] == 2 and sale["amount"] == 7 and [e for e in events if e[0].startswith("deadlock")] == [("deadlock_retry", 1)]
    assert _balance(fake_db) == 7.0  # recorded exactly once


def test_deadlock_gives_up_after_retries_and_other_errors_are_not_retried(fake_db, monkeypatch):
    calls = {"n": 0}

    def always(db, **kw):
        calls["n"] += 1
        raise sales_repository.ProcedureError(1205, "deadlock victim")

    monkeypatch.setattr(sales_repository, "record_sale", always)
    with pytest.raises(sales_repository.ProcedureError) as exc:
        sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=7, category="x")
    assert is_deadlock(exc.value) and calls["n"] == 4  # 1 try + 3 retries

    calls["n"] = 0

    def other(db, **kw):
        calls["n"] += 1
        raise sales_repository.ProcedureError(547, "constraint")

    monkeypatch.setattr(sales_repository, "record_sale", other)
    with pytest.raises(sales_repository.ProcedureError):
        sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=7, category="x")
    assert calls["n"] == 1


def test_cash_is_scoped_per_org(fake_db):
    sales_service.create_sale(fake_db, org_id=ORG, user_id="u1", amount=10, category="x")
    sales_service.create_sale(fake_db, org_id=OTHER, user_id="u2", amount=99, category="x")
    assert _balance(fake_db) == 10.0 and _balance(fake_db, OTHER) == 99.0
    assert all(e["org_id"] == ORG for e in cash_service.list_ledger(fake_db, org_id=ORG))
