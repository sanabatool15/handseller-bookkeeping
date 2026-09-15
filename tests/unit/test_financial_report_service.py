import datetime as dt

from services import expenses_service, sales_service
from services.financial_report_service import monthly_ledger_csv, monthly_summary


def test_monthly_summary_computes_net_profit(fake_db):
    now = dt.datetime.utcnow()
    sales_service.create_sale(fake_db, org_id="org-1", user_id="u1", amount=100.0, category="retail")
    expenses_service.create_expense(fake_db, org_id="org-1", user_id="u1", amount=40.0, category="rent")

    summary = monthly_summary(fake_db, org_id="org-1", year=now.year, month=now.month)
    assert summary["total_sales"] == 100.0
    assert summary["total_expenses"] == 40.0
    assert summary["net_profit"] == 60.0


def test_monthly_ledger_csv_contains_rows(fake_db):
    now = dt.datetime.utcnow()
    sales_service.create_sale(fake_db, org_id="org-1", user_id="u1", amount=100.0, category="retail")
    csv_text = monthly_ledger_csv(fake_db, org_id="org-1", year=now.year, month=now.month)
    assert "sale" in csv_text
    assert "type,date,amount" in csv_text
