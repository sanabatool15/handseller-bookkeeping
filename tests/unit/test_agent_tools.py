"""Unit tests for isolated agents/tool functions with mocked repositories."""
from unittest.mock import patch

from app.agents import tools
from app.agents.financial_advisor import run_financial_advisor


def test_fetch_monthly_report_tool_delegates_to_service():
    with patch("app.repository.sales_repository.list_sales_for_period", return_value=[]), patch(
        "app.repository.expenses_repository.list_expenses_for_period", return_value=[]
    ):
        result = tools.fetch_monthly_report(org_id="org-1", month=3, year=2026)

    assert result["month"] == 3
    assert result["total_sales"] == 0


def test_fetch_recent_transactions_tool_delegates_to_repositories():
    with patch(
        "app.repository.sales_repository.list_recent_sales", return_value=[{"id": "s1"}]
    ) as mock_sales, patch(
        "app.repository.expenses_repository.list_recent_expenses", return_value=[{"id": "e1"}]
    ) as mock_expenses:
        result = tools.fetch_recent_transactions(org_id="org-1", limit=5)

    mock_sales.assert_called_once_with(org_id="org-1", limit=5)
    mock_expenses.assert_called_once_with(org_id="org-1", limit=5)
    assert result["recent_sales"] == [{"id": "s1"}]
    assert result["recent_expenses"] == [{"id": "e1"}]


def test_run_financial_advisor_rule_based_fallback_flags_top_cost_drivers():
    sales = [{"amount": "10.00", "sale_date": "2026-01-01"}]
    expenses = [
        {"amount": "80.00", "category": "raw materials", "expense_date": "2026-01-01"},
        {"amount": "20.00", "category": "packaging", "expense_date": "2026-01-01"},
    ]
    with patch(
        "app.repository.sales_repository.list_sales_for_period", return_value=sales
    ), patch(
        "app.repository.expenses_repository.list_expenses_for_period", return_value=expenses
    ):
        result = run_financial_advisor(org_id="org-1", month=1, year=2026)

    assert "action_summary" in result
    assert result["insights"]["expense_breakdown"]["top_cost_drivers"][0] == "raw materials"
    assert "cost_reduction_suggestions" in result["insights"]
    assert "pricing_volume_suggestion" in result["insights"]
