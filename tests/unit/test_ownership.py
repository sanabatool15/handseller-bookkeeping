from repository.base import get_ownership
from services import sales_service


def test_get_ownership_true_for_correct_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="retail")
    assert get_ownership(fake_db, table="sales", record_id=sale["id"], org_id="org-1") is True


def test_get_ownership_false_for_wrong_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="retail")
    assert get_ownership(fake_db, table="sales", record_id=sale["id"], org_id="org-2") is False


def test_get_ownership_false_for_nonexistent_record(fake_db):
    assert get_ownership(fake_db, table="sales", record_id="does-not-exist", org_id="org-1") is False
