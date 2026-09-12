"""FastMCP server exposing the bookkeeping application as tools for external
LLM clients (Claude Desktop, ChatGPT, etc).

Every tool requires `org_id` and `user_id` and re-verifies organization
membership via the repository layer's get_ownership() before touching any
data -- the same structural multi-tenancy guarantee as the HTTP API.

Run with:  python -m app.mcp.server
"""
from datetime import date

from fastmcp import FastMCP

from app.repository.org_repository import get_ownership
from app.schemas.expenses import ExpenseCreate
from app.schemas.sales import SaleCreate
from app.services import agent_service, expenses_service, reports_service, sales_service

mcp = FastMCP("handseller-bookkeeping")


def _require_membership(user_id: str, org_id: str) -> None:
    if not get_ownership(user_id=user_id, org_id=org_id):
        raise PermissionError(f"User {user_id} is not a member of org {org_id}")


@mcp.tool()
def log_sale(
    org_id: str,
    user_id: str,
    amount: float,
    sale_date: str,
    voucher_reference: str | None = None,
) -> dict:
    """Log a sale for an organization. sale_date is an ISO date (YYYY-MM-DD)."""
    _require_membership(user_id, org_id)
    payload = SaleCreate(
        amount=amount, sale_date=date.fromisoformat(sale_date), voucher_reference=voucher_reference
    )
    return sales_service.log_sale(org_id=org_id, user_id=user_id, payload=payload)


@mcp.tool()
def log_expense(
    org_id: str,
    user_id: str,
    amount: float,
    category: str,
    expense_date: str,
    description: str | None = None,
) -> dict:
    """Log an expense for an organization. expense_date is an ISO date (YYYY-MM-DD)."""
    _require_membership(user_id, org_id)
    payload = ExpenseCreate(
        amount=amount,
        category=category,
        description=description,
        expense_date=date.fromisoformat(expense_date),
    )
    return expenses_service.log_expense(org_id=org_id, user_id=user_id, payload=payload)


@mcp.tool()
def get_monthly_report(org_id: str, user_id: str, month: int, year: int) -> dict:
    """Get total sales, total expenses, net profit/loss and profitability for a month."""
    _require_membership(user_id, org_id)
    return reports_service.get_monthly_report(org_id=org_id, month=month, year=year).model_dump()


@mcp.tool()
def analyze_expenses(org_id: str, user_id: str, month: int, year: int) -> dict:
    """Get expense totals grouped by category with percentage-of-total and top cost drivers."""
    _require_membership(user_id, org_id)
    return reports_service.get_expense_breakdown(org_id=org_id, month=month, year=year).model_dump()


@mcp.tool()
def run_financial_agent(org_id: str, user_id: str, month: int, year: int) -> dict:
    """Run the autonomous financial advisor agent for a month and log the execution."""
    _require_membership(user_id, org_id)
    return agent_service.run_agent(org_id=org_id, user_id=user_id, month=month, year=year)


if __name__ == "__main__":
    mcp.run()
