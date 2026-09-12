"""Reporting/analytics endpoints. Delegates all logic to app.services.reports_service."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.core.security import CurrentUser, get_current_user
from app.models.reports import ExpenseAnalytics, MonthlyReport
from app.services import reports_service

router = APIRouter(prefix="/orgs/{org_id}/reports", tags=["reports"])


@router.get("/monthly", response_model=MonthlyReport)
def get_monthly_report(
    org_id: str,
    month: str = Query(..., description="Month formatted YYYY-MM, e.g. 2025-01."),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Total sales, total expenses, and net profit/loss for the requested month."""
    return reports_service.get_monthly_report(current_user.user_id, org_id, month)


@router.get("/expense-analytics", response_model=ExpenseAnalytics)
def get_expense_analytics(
    org_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Aggregates expenses by category to show where the business spends the most."""
    return reports_service.get_expense_analytics(
        current_user.user_id, org_id, start_date, end_date
    )
