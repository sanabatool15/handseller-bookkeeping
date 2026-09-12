from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user
from app.models.reports import MonthlyReport
from app.services import reports_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly", response_model=MonthlyReport)
def get_monthly_report(
    year: int,
    month: int,
    current: CurrentUser = Depends(get_current_user),
) -> MonthlyReport:
    return reports_service.get_monthly_report(current, year, month)
