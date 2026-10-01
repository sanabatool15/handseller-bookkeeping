"""F4: expenses and amount edits move cash. Services run against fakes that mirror usp_RecordExpense / usp_VoidExpense /
usp_AdjustEntryAmount (same statuses, same ledger rows, scoping by id AND org_id)."""
import datetime as dt

import pytest

from core.db import is_deadlock
from repository import expenses_repository
from repository.base import ProcedureError
from services import cash_service, expenses_service, products_service, sales_service

ORG, OTHER = "org-1", "org-2"


def _balance(db, org=ORG):
    return cash_service.get_balance(db, org_id=org)["balance"]


def _ledger(db, org=ORG, **kw):
    return cash_service.list_ledger(db, org_id=org, **kw)


def _expense(db, amount=30.0, org=ORG, **kw):
    return expenses_service.create_expense(db, org_id=org, user_id="u1", amount=amount, category=kw.pop("category", "rent"), **kw)


def _sale(db, amount=100.0, org=ORG):
    return sales_service.create_sale(db, org_id=org, user_id="u1", amount=amount, category="retail")


def test_expense_reduces_balance_and_writes_a_negative_ledger_row(fake_db):
    _sale(fake_db, 100.0)
    exp = _expense(fake_db, 30.0)
    assert _balance(fake_db) == 70.0
    row = _ledger(fake_db, entry_type="expense")[0]
    assert row["amount"] == -30.0 and row["balance_after"] == 70.0 and row["ref_type"] == "expense" and row["ref_id"] == exp["id"]


def test_balance_may_go_negative_when_spending_before_cashing_up(fake_db):
    _expense(fake_db, 25.0)
    assert _balance(fake_db) == -25.0
    assert _ledger(fake_db)[0]["balance_after"] == -25.0


def test_delete_expense_restores_balance_with_a_void_entry(fake_db):
    _sale(fake_db, 100.0)
    exp = _expense(fake_db, 30.0)
    expenses_service.delete_expense(fake_db, org_id=ORG, expense_id=exp["id"], user_id="u1")
    assert _balance(fake_db) == 100.0
    types = [e["entry_type"] for e in _ledger(fake_db)]
    assert types == ["expense_void", "expense", "sale"]
    assert _ledger(fake_db, entry_type="expense_void")[0]["amount"] == 30.0
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.get_expense(fake_db, org_id=ORG, expense_id=exp["id"])
    with pytest.raises(expenses_service.NotFoundError):  # second void: nothing left
        expenses_service.delete_expense(fake_db, org_id=ORG, expense_id=exp["id"])


def test_delete_after_amount_edit_reverses_the_adjusted_total(fake_db):
    exp = _expense(fake_db, 30.0)
    expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": 50.0})
    assert _balance(fake_db) == -50.0
    expenses_service.delete_expense(fake_db, org_id=ORG, expense_id=exp["id"])
    assert _balance(fake_db) == 0.0


def test_expense_amount_edit_posts_negative_delta_for_increase_and_positive_for_decrease(fake_db):
    exp = _expense(fake_db, 30.0)
    up = expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": 45.5, "category": "fees"})
    assert up["amount"] == 45.5 and up["category"] == "fees"  # other fields change in the same call
    assert _balance(fake_db) == -45.5
    adj = _ledger(fake_db, entry_type="adjustment")
    assert adj[0]["amount"] == -15.5 and adj[0]["balance_after"] == -45.5 and adj[0]["ref_type"] == "expense"
    expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": 40.0})
    assert _balance(fake_db) == -40.0 and _ledger(fake_db, entry_type="adjustment")[0]["amount"] == 5.5


def test_same_amount_posts_no_adjustment(fake_db):
    exp = _expense(fake_db, 30.0)
    out = expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": 30.0, "description": "d"})
    assert out["description"] == "d" and _ledger(fake_db, entry_type="adjustment") == [] and _balance(fake_db) == -30.0


def test_sale_amount_edit_posts_positive_delta(fake_db):
    sale = _sale(fake_db, 50.0)
    out = sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 80.0, "description": "x"}, user_id="u1")
    assert out["amount"] == 80.0 and out["description"] == "x"
    assert _balance(fake_db) == 80.0
    adj = _ledger(fake_db, entry_type="adjustment")[0]
    assert adj["amount"] == 30.0 and adj["balance_after"] == 80.0 and adj["ref_type"] == "sale" and adj["created_by"] == "u1"
    sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 20.0})
    assert _balance(fake_db) == 20.0


def test_void_sale_after_amount_edit_reverses_sale_plus_adjustment(fake_db):
    """balance == SUM(ledger) must survive: the void reverses the 'sale' entry AND the 'adjustment' entries."""
    sale = _sale(fake_db, 50.0)
    sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 80.0})
    sales_service.delete_sale(fake_db, org_id=ORG, sale_id=sale["id"])
    assert _balance(fake_db) == 0.0
    assert sum(e["amount"] for e in _ledger(fake_db)) == 0.0


def test_item_sale_amount_edit_is_refused_and_changes_nothing(fake_db):
    p = products_service.create_product(fake_db, org_id=ORG, user_id="u", name="Mug", sku="M", price=10.0, stock_qty=5)
    sale = sales_service.create_sale(fake_db, org_id=ORG, user_id="u", items=[{"product_id": p["id"], "quantity": 1}])
    with pytest.raises(sales_service.ValidationError, match="line items"):
        sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 1.0})
    assert _balance(fake_db) == 10.0 and _ledger(fake_db, entry_type="adjustment") == []
    assert sales_service.get_sale(fake_db, org_id=ORG, sale_id=sale["id"])["amount"] == 10.0


def test_cross_tenant_is_not_found_on_every_expense_verb_and_changes_nothing(fake_db):
    exp = _expense(fake_db, 30.0)
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.get_expense(fake_db, org_id=OTHER, expense_id=exp["id"])
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.update_expense(fake_db, org_id=OTHER, expense_id=exp["id"], updates={"amount": 1.0})
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.update_expense(fake_db, org_id=OTHER, expense_id=exp["id"], updates={"category": "x"})
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.delete_expense(fake_db, org_id=OTHER, expense_id=exp["id"])
    assert expenses_service.get_expense(fake_db, org_id=ORG, expense_id=exp["id"])["amount"] == 30.0
    assert _balance(fake_db) == -30.0 and _balance(fake_db, OTHER) == 0.0 and _ledger(fake_db, OTHER) == []


def test_cross_tenant_sale_amount_edit_is_not_found(fake_db):
    sale = _sale(fake_db, 50.0)
    with pytest.raises(sales_service.NotFoundError):
        sales_service.update_sale(fake_db, org_id=OTHER, sale_id=sale["id"], updates={"amount": 1.0})
    assert _balance(fake_db) == 50.0


@pytest.mark.parametrize("amount", [0, -1, 1_000_000_000_000.0])
def test_expense_amount_validation(fake_db, amount):
    with pytest.raises(expenses_service.ValidationError):
        _expense(fake_db, amount)
    exp = _expense(fake_db, 5.0)
    with pytest.raises(expenses_service.ValidationError):
        expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": amount})
    assert _balance(fake_db) == -5.0


def test_expense_text_length_validation(fake_db):
    with pytest.raises(expenses_service.ValidationError):
        _expense(fake_db, 1.0, category="c" * 101)
    with pytest.raises(expenses_service.ValidationError):
        _expense(fake_db, 1.0, voucher_reference="v" * 201)


def test_deadlock_on_expense_is_retried_once(fake_db, monkeypatch):
    real, calls = expenses_repository.record_expense, []

    def flaky(db, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise ProcedureError(1205, "deadlock victim")
        return real(db, **kw)

    monkeypatch.setattr(expenses_repository, "record_expense", flaky)
    events = []
    expenses_service.create_expense(fake_db, org_id=ORG, user_id="u", amount=5.0, category="c", on_event=lambda step, **i: events.append(step))
    assert len(calls) == 2 and [e for e in events if e.startswith("deadlock")] == ["deadlock_retry"] and _balance(fake_db) == -5.0
    assert is_deadlock(ProcedureError(1205, "x"))


# ---- ledger filters and the monthly summary ------------------------------------------------------------------------

def _post(store, org, entry_type, amount, day):
    from tests.fake_repos import post_cash

    post_cash(store, org, entry_type, amount, "sale" if "sale" in entry_type else "expense", "r", "u", day)


def test_ledger_filters_by_type_and_date_range_and_validates(fake_db, sql_store):
    _post(sql_store, ORG, "sale", 100.0, "2026-01-10")
    _post(sql_store, ORG, "expense", -20.0, "2026-01-20")
    _post(sql_store, ORG, "sale", 50.0, "2026-02-05")
    _post(sql_store, OTHER, "sale", 999.0, "2026-01-10")
    assert [e["amount"] for e in _ledger(fake_db, entry_type="sale")] == [50.0, 100.0]
    assert [e["amount"] for e in _ledger(fake_db, date_from=dt.date(2026, 1, 15))] == [50.0, -20.0]
    assert [e["amount"] for e in _ledger(fake_db, date_to=dt.date(2026, 1, 20))] == [-20.0, 100.0]  # inclusive
    both = _ledger(fake_db, entry_type="sale", date_from=dt.date(2026, 1, 1), date_to=dt.date(2026, 1, 31))
    assert [e["amount"] for e in both] == [100.0]
    assert _ledger(fake_db, entry_type="adjustment") == []
    assert len(_ledger(fake_db, limit=1, offset=1)) == 1
    with pytest.raises(cash_service.ValidationError):
        _ledger(fake_db, entry_type="bogus")
    with pytest.raises(cash_service.ValidationError):
        _ledger(fake_db, date_from=dt.date(2026, 2, 1), date_to=dt.date(2026, 1, 1))


def test_summary_math_opening_in_out_closing_and_by_type(fake_db, sql_store):
    _post(sql_store, ORG, "sale", 100.0, "2026-01-10")       # before the month => opening
    _post(sql_store, ORG, "expense", -20.0, "2026-01-31")    # before
    _post(sql_store, ORG, "sale", 70.0, "2026-02-01")        # inside (first day)
    _post(sql_store, ORG, "sale", 30.0, "2026-02-28")        # inside (last day)
    _post(sql_store, ORG, "expense", -45.5, "2026-02-14")
    _post(sql_store, ORG, "adjustment", -4.5, "2026-02-14")
    _post(sql_store, ORG, "sale_void", -30.0, "2026-02-15")
    _post(sql_store, ORG, "sale", 500.0, "2026-03-01")       # after the month: ignored
    _post(sql_store, OTHER, "sale", 7777.0, "2026-02-10")    # other tenant: ignored
    s = cash_service.get_summary(fake_db, org_id=ORG, year=2026, month=2)
    assert s["opening_balance"] == 80.0
    assert s["total_in"] == 100.0 and s["total_out"] == 80.0  # out = magnitude of the negative amounts
    assert s["closing_balance"] == 100.0 == s["opening_balance"] + s["total_in"] - s["total_out"]
    assert s["by_type"] == {"sale": 100.0, "sale_void": -30.0, "expense": -45.5, "expense_void": 0.0, "adjustment": -4.5}
    assert (s["year"], s["month"]) == (2026, 2)


def test_summary_for_month_without_rows_is_all_zero_but_carries_the_opening_balance(fake_db, sql_store):
    empty = cash_service.get_summary(fake_db, org_id=ORG, year=2026, month=5)
    assert empty["opening_balance"] == empty["closing_balance"] == empty["total_in"] == empty["total_out"] == 0.0
    assert set(empty["by_type"]) == set(cash_service.ENTRY_TYPES) and not any(empty["by_type"].values())
    _post(sql_store, ORG, "sale", 40.0, "2026-01-02")
    quiet = cash_service.get_summary(fake_db, org_id=ORG, year=2026, month=5)
    assert quiet["opening_balance"] == quiet["closing_balance"] == 40.0 and quiet["total_in"] == 0.0


def test_summary_defaults_to_current_month_and_validates(fake_db):
    today = dt.datetime.now(dt.timezone.utc)
    s = cash_service.get_summary(fake_db, org_id=ORG)
    assert (s["year"], s["month"]) == (today.year, today.month)
    for kw in ({"month": 0}, {"month": 13}, {"year": 1999}, {"year": 2101}):
        with pytest.raises(cash_service.ValidationError):
            cash_service.get_summary(fake_db, org_id=ORG, **{"year": 2026, "month": 1, **kw})
