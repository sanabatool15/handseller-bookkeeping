from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class MonthlyReportQuery(BaseModel):
    """Query params for the monthly report endpoint: a `YYYY-MM` string."""

    month: str = Field(..., description="Month to report on, formatted YYYY-MM, e.g. 2025-01.")

    @field_validator("month")
    @classmethod
    def month_format(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValueError("'month' must be formatted as YYYY-MM, e.g. 2025-01")
        year_str, month_str = parts
        if not (year_str.isdigit() and month_str.isdigit()):
            raise ValueError("'month' must be formatted as YYYY-MM, e.g. 2025-01")
        month_int = int(month_str)
        if not 1 <= month_int <= 12:
            raise ValueError("'month' must contain a valid month between 01 and 12")
        return v


class MonthlyReport(BaseModel):
    org_id: str
    month: str
    total_sales: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    sales_count: int
    expenses_count: int


class ExpenseCategoryBreakdown(BaseModel):
    category: str
    total_amount: Decimal
    expense_count: int
    percentage_of_total: Decimal


class ExpenseAnalytics(BaseModel):
    org_id: str
    total_expenses: Decimal
    categories: list[ExpenseCategoryBreakdown]
    top_category: str | None = None
