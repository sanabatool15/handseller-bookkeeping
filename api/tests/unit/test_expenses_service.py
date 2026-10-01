import pytest

from services import expenses_service


def test_create_expense_success(fake_db):
    expense = expenses_service.create_expense(fake_db, org_id="org-1", user_id="user-1", amount=42.0, category="rent", voucher_reference="V-1")
    assert expense["amount"] == 42.0
    assert expense["voucher_reference"] == "V-1"


def test_create_expense_rejects_non_positive_amount(fake_db):
    with pytest.raises(expenses_service.ValidationError):
        expenses_service.create_expense(fake_db, org_id="org-1", user_id="user-1", amount=0, category="rent")


def test_expense_scoped_by_org(fake_db):
    expense = expenses_service.create_expense(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="rent")

    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.get_expense(fake_db, org_id="org-2", expense_id=expense["id"])

    fetched = expenses_service.get_expense(fake_db, org_id="org-1", expense_id=expense["id"])
    assert fetched["id"] == expense["id"]


def test_update_expense_scoped_to_org(fake_db):
    expense = expenses_service.create_expense(fake_db, org_id="org-1", user_id="u", amount=10.0, category="rent")
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.update_expense(fake_db, org_id="org-2", expense_id=expense["id"], updates={"amount": 99})
    updated = expenses_service.update_expense(fake_db, org_id="org-1", expense_id=expense["id"], updates={"amount": 12.5, "category": None})
    assert updated["amount"] == 12.5 and updated["category"] == "rent"  # None values are ignored


def test_update_expense_rejects_non_positive_amount(fake_db):
    expense = expenses_service.create_expense(fake_db, org_id="org-1", user_id="u", amount=10.0, category="rent")
    with pytest.raises(expenses_service.ValidationError):
        expenses_service.update_expense(fake_db, org_id="org-1", expense_id=expense["id"], updates={"amount": 0})


def test_delete_expense_scoped_to_org(fake_db):
    expense = expenses_service.create_expense(fake_db, org_id="org-1", user_id="u", amount=10.0, category="rent")
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.delete_expense(fake_db, org_id="org-2", expense_id=expense["id"])
    expenses_service.delete_expense(fake_db, org_id="org-1", expense_id=expense["id"])
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.get_expense(fake_db, org_id="org-1", expense_id=expense["id"])


def test_list_expenses_only_returns_org_scoped_rows(fake_db):
    expenses_service.create_expense(fake_db, org_id="org-1", user_id="u", amount=1.0, category="rent")
    expenses_service.create_expense(fake_db, org_id="org-2", user_id="u", amount=2.0, category="rent")
    rows = expenses_service.list_expenses(fake_db, org_id="org-1")
    assert [r["org_id"] for r in rows] == ["org-1"]
