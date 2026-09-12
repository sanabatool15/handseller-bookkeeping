"""Tool functions exposed to the financial advisor agent.

These are plain Python functions with docstrings/type hints so they can be
wrapped either as OpenAI Agents SDK `@function_tool`s (see financial_advisor.py)
or as FastMCP tools (see app/mcp/server.py). They call only the services
layer — never the repository or Supabase client directly.
"""
from app.services import reports_service
from app.repository import sales_repository, expenses_repository


def fetch_monthly_report(org_id: str, month: int, year: int) -> dict:
    """Fetch total sales, total expenses, and net profit/loss for a given month."""
    report = reports_service.get_monthly_report(org_id=org_id, month=month, year=year)
    return report.model_dump()


def fetch_expense_breakdown(org_id: str, month: int, year: int) -> dict:
    """Fetch expense totals grouped by category, with percentage-of-total and
    top cost drivers, for a given month."""
    breakdown = reports_service.get_expense_breakdown(org_id=org_id, month=month, year=year)
    return breakdown.model_dump()


def fetch_recent_transactions(org_id: str, limit: int = 10) -> dict:
    """Fetch the most recent sales and expenses for an organization."""
    return {
        "recent_sales": sales_repository.list_recent_sales(org_id=org_id, limit=limit),
        "recent_expenses": expenses_repository.list_recent_expenses(org_id=org_id, limit=limit),
    }
