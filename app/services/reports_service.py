"""Monthly report calculations. Delegates persistence to the repository
layer and does the total sales / total expenses / net profit math here."""

import calendar
from datetime import date

from fastapi import HTTPException, status

from app.auth import CurrentUser
from app.models.reports import MonthlyReport
from app.repository import expenses_repository, sales_repository


def get_monthly_report(current: CurrentUser, year: int, month: int) -> MonthlyReport:
    if not 1 <= month <= 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month must be between 1 and 12")

    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last_day)

    sales = sales_repository.list_sales_for_org(current.org_id, start, end)
    expenses = expenses_repository.list_expenses_for_org(current.org_id, start, end)

    total_sales = sum(float(row["amount"]) for row in sales)
    total_expenses = sum(float(row["amount"]) for row in expenses)

    return MonthlyReport(
        org_id=str(current.org_id),
        year=year,
        month=month,
        total_sales=round(total_sales, 2),
        total_expenses=round(total_expenses, 2),
        net_profit=round(total_sales - total_expenses, 2),
        sales_count=len(sales),
        expenses_count=len(expenses),
    )
