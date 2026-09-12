from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, get_current_user
from app.schemas.reports import ExpenseBreakdownReport, MonthlyReport
from app.services import reports_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly", response_model=MonthlyReport)
def monthly_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return reports_service.get_monthly_report(org_id=current_user.org_id, month=month, year=year)


@router.get("/expense-breakdown", response_model=ExpenseBreakdownReport)
def expense_breakdown(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    current_user: CurrentUser = Depends(get_current_user),
):
    return reports_service.get_expense_breakdown(org_id=current_user.org_id, month=month, year=year)
