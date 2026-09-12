"""Unit tests for services/reports_service.py calculations, with the
repository layer mocked out."""
from unittest.mock import patch

from app.services import reports_service


SALES = [
    {"id": "s1", "amount": "100.00", "sale_date": "2026-01-05"},
    {"id": "s2", "amount": "50.50", "sale_date": "2026-01-20"},
]
EXPENSES = [
    {"id": "e1", "amount": "30.00", "category": "raw materials", "expense_date": "2026-01-03"},
    {"id": "e2", "amount": "10.00", "category": "packaging", "expense_date": "2026-01-10"},
    {"id": "e3", "amount": "20.00", "category": "raw materials", "expense_date": "2026-01-15"},
]


def test_monthly_report_calculates_totals_and_profitability():
    with patch(
        "app.repository.sales_repository.list_sales_for_period", return_value=SALES
    ), patch(
        "app.repository.expenses_repository.list_expenses_for_period", return_value=EXPENSES
    ):
        report = reports_service.get_monthly_report(org_id="org-1", month=1, year=2026)

    assert report.total_sales == 150.50
    assert report.total_expenses == 60.00
    assert report.net_profit_loss == 90.50
    assert report.is_profitable is True


def test_monthly_report_flags_loss():
    with patch("app.repository.sales_repository.list_sales_for_period", return_value=[]), patch(
        "app.repository.expenses_repository.list_expenses_for_period", return_value=EXPENSES
    ):
        report = reports_service.get_monthly_report(org_id="org-1", month=1, year=2026)

    assert report.total_sales == 0
    assert report.net_profit_loss == -60.00
    assert report.is_profitable is False


def test_expense_breakdown_groups_and_computes_percentages():
    with patch(
        "app.repository.expenses_repository.list_expenses_for_period", return_value=EXPENSES
    ):
        breakdown = reports_service.get_expense_breakdown(org_id="org-1", month=1, year=2026)

    assert breakdown.total_expenses == 60.00
    by_category = {c.category: c for c in breakdown.breakdown}
    assert by_category["raw materials"].total_amount == 50.00
    assert by_category["raw materials"].percentage_of_total == round(50 / 60 * 100, 2)
    assert by_category["packaging"].total_amount == 10.00
    assert breakdown.top_cost_drivers[0] == "raw materials"


def test_expense_breakdown_handles_zero_expenses():
    with patch("app.repository.expenses_repository.list_expenses_for_period", return_value=[]):
        breakdown = reports_service.get_expense_breakdown(org_id="org-1", month=1, year=2026)

    assert breakdown.total_expenses == 0
    assert breakdown.breakdown == []
    assert breakdown.top_cost_drivers == []
