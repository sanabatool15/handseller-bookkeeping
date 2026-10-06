"""Agent-facing tool wrappers around the existing bookkeeping services.

These are thin `@function_tool`-wrapped closures over `org_id` (and, for the
record tools, `user_id`) — the org/user identity comes from the Inngest job
context that builds the agents for a given run, never from the LLM, so a
tool call can never be tricked into acting on a different org's data.

No business logic lives here: every function below delegates straight into
`services/financial_report_service.py`, `services/expenses_service.py`, or
`services/sales_service.py`, which is the layer CLAUDE.md requires for
validation + business logic. This module only adapts those existing service
calls into the shape the OpenAI Agents SDK expects for a tool.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from supabase import Client

from services import expenses_service, financial_report_service, sales_service
from ai_agents.tools.deep_link import build_deep_link
from ai_agents.tools.web_search import web_search as _web_search

try:
    from agents import function_tool as _function_tool
except ImportError:  # pragma: no cover - handled by callers checking _sdk_available
    _function_tool = None


def _current_year_month() -> tuple[int, int]:
    now = dt.datetime.utcnow()
    return now.year, now.month


def build_investigate_tools(db: Client, *, org_id: str) -> list[Any]:
    """Tools scoped to `investigate_agent`: read-only summary/breakdown
    queries plus web_search. No record-mutating tool is ever included here.
    """
    if _function_tool is None:
        raise RuntimeError("openai-agents is not installed")

    @_function_tool
    def get_monthly_summary(year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Returns this org's total sales, total expenses, and net profit
        for the given year/month (defaults to the current month)."""
        y, m = (year, month) if year and month else _current_year_month()
        return financial_report_service.monthly_summary(db, org_id=org_id, year=y, month=m)

    @_function_tool
    def get_expense_breakdown_by_category(year: int | None = None, month: int | None = None) -> dict[str, float]:
        """Returns {category: total_amount} for this org's expenses in the
        given year/month (defaults to the current month)."""
        y, m = (year, month) if year and month else _current_year_month()
        return financial_report_service.expense_breakdown_by_category(db, org_id=org_id, year=y, month=m)

    @_function_tool
    def get_sales_breakdown_by_category(year: int | None = None, month: int | None = None) -> dict[str, float]:
        """Returns {category: total_amount} for this org's sales in the
        given year/month (defaults to the current month)."""
        y, m = (year, month) if year and month else _current_year_month()
        return financial_report_service.sales_breakdown_by_category(db, org_id=org_id, year=y, month=m)

    @_function_tool
    async def web_search(query: str) -> list[dict[str, str]]:
        """Searches the web for external context (e.g. supplier pricing) on
        a specific cost driver already identified from the org's own data.
        Never call this before you have a concrete category or line item to
        search for."""
        return await _web_search(query)

    return [
        get_monthly_summary,
        get_expense_breakdown_by_category,
        get_sales_breakdown_by_category,
        web_search,
    ]


def build_record_tools(db: Client, *, org_id: str, user_id: str) -> list[Any]:
    """Tools scoped to `record_agent`: create-expense/create-sale plus the
    deep-link builder used to hand the user a reference. No read/investigate
    tool is ever included here.
    """
    if _function_tool is None:
        raise RuntimeError("openai-agents is not installed")

    @_function_tool
    def create_expense_record(
        amount: float,
        category: str = "general",
        voucher_reference: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Records a new expense for this org. `amount` must be positive."""
        return expenses_service.create_expense(
            db,
            org_id=org_id,
            user_id=user_id,
            amount=amount,
            category=category,
            voucher_reference=voucher_reference,
            description=description,
        )

    @_function_tool
    def create_sales_record(
        amount: float,
        category: str = "general",
        customer_name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Records a new sale for this org. `amount` must be positive."""
        return sales_service.create_sale(
            db,
            org_id=org_id,
            user_id=user_id,
            amount=amount,
            category=category,
            description=description,
            customer_name=customer_name,
        )

    @_function_tool
    def deep_link(resource: str, resource_id: str | None = None) -> str:
        """Builds a client-side deep link back to a created record, e.g.
        resource='sales' or resource='expenses'."""
        return build_deep_link(org_id=org_id, resource=resource, resource_id=resource_id)

    return [create_expense_record, create_sales_record, deep_link]
