import pytest

from services import sales_service


def test_create_sale_success(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=100.0, category="retail")
    assert sale["amount"] == 100.0
    assert sale["org_id"] == "org-1"


def test_create_sale_rejects_non_positive_amount(fake_db):
    with pytest.raises(sales_service.ValidationError):
        sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=0, category="retail")
    with pytest.raises(sales_service.ValidationError):
        sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=-5, category="retail")


def test_get_sale_scoped_to_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=50.0, category="retail")

    # Fetching from the correct org works.
    fetched = sales_service.get_sale(fake_db, org_id="org-1", sale_id=sale["id"])
    assert fetched["id"] == sale["id"]

    # The SAME sale_id under a DIFFERENT org must not be visible (structural
    # multi-tenancy — this is the check-then-fetch vulnerability regression test).
    with pytest.raises(sales_service.NotFoundError):
        sales_service.get_sale(fake_db, org_id="org-2", sale_id=sale["id"])


def test_update_sale_scoped_to_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=50.0, category="retail")

    with pytest.raises(sales_service.NotFoundError):
        sales_service.update_sale(fake_db, org_id="org-2", sale_id=sale["id"], updates={"amount": 999})

    updated = sales_service.update_sale(fake_db, org_id="org-1", sale_id=sale["id"], updates={"amount": 75.0})
    assert updated["amount"] == 75.0


def test_delete_sale_scoped_to_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=50.0, category="retail")

    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(fake_db, org_id="org-2", sale_id=sale["id"])

    sales_service.delete_sale(fake_db, org_id="org-1", sale_id=sale["id"])
    with pytest.raises(sales_service.NotFoundError):
        sales_service.get_sale(fake_db, org_id="org-1", sale_id=sale["id"])


def test_list_sales_only_returns_org_scoped_rows(fake_db):
    sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="retail")
    sales_service.create_sale(fake_db, org_id="org-2", user_id="user-2", amount=20.0, category="retail")

    org1_sales = sales_service.list_sales(fake_db, org_id="org-1")
    assert len(org1_sales) == 1
    assert org1_sales[0]["org_id"] == "org-1"
