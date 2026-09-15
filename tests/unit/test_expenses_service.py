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
