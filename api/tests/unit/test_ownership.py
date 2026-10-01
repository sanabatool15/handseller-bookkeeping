"""get_ownership: the fake enforces id+org_id like the SQL; the real function is checked with a recording Db."""
import pytest

from repository import base
from services import expenses_service, sales_service
from tests.fake_repos import REAL_GET_OWNERSHIP


def test_get_ownership_true_for_correct_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="retail")
    assert base.get_ownership(fake_db, table="sales", record_id=sale["id"], org_id="org-1") is True


def test_get_ownership_false_for_wrong_org(fake_db):
    sale = sales_service.create_sale(fake_db, org_id="org-1", user_id="user-1", amount=10.0, category="retail")
    assert base.get_ownership(fake_db, table="sales", record_id=sale["id"], org_id="org-2") is False


def test_get_ownership_false_for_nonexistent_record(fake_db):
    assert base.get_ownership(fake_db, table="sales", record_id="does-not-exist", org_id="org-1") is False


def test_get_ownership_expenses_scoped_by_org(fake_db):
    e = expenses_service.create_expense(fake_db, org_id="org-1", user_id="u", amount=5.0, category="rent")
    assert base.get_ownership(fake_db, table="expenses", record_id=e["id"], org_id="org-1") is True
    assert base.get_ownership(fake_db, table="expenses", record_id=e["id"], org_id="org-2") is False


class _RecordingDb:
    def __init__(self, row):
        self.row, self.calls = row, []

    def query_one(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return self.row


def test_real_get_ownership_sends_id_and_org_id_in_one_statement():
    db = _RecordingDb({"ok": 1})
    assert REAL_GET_OWNERSHIP(db, table="sales", record_id="r1", org_id="o1") is True
    sql, params = db.calls[0]
    assert "id = ?" in sql and "org_id = ?" in sql and params == ("r1", "o1")
    assert REAL_GET_OWNERSHIP(_RecordingDb(None), table="sales", record_id="r1", org_id="o1") is False


@pytest.mark.parametrize("table", ["orgs", "sales; DROP TABLE sales", "", None])
def test_real_get_ownership_rejects_tables_outside_the_allow_list(table):
    db = _RecordingDb({"ok": 1})
    with pytest.raises(base.RepositoryError):
        REAL_GET_OWNERSHIP(db, table=table, record_id="r1", org_id="o1")
    assert db.calls == []  # nothing was sent to the database
