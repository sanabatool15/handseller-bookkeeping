"""Expense endpoints. Delegates all logic to app.services.expenses_service.

`org_id` always comes from the URL path (never the body) and is verified
against the authenticated user's ownership inside the service layer.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.core.security import CurrentUser, get_current_user
from app.models.expenses import ExpenseCreate, ExpenseOut
from app.services import expenses_service

router = APIRouter(prefix="/orgs/{org_id}/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def log_expense(
    org_id: str,
    payload: ExpenseCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return expenses_service.log_expense(current_user.user_id, org_id, payload)


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    org_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return expenses_service.list_expenses(current_user.user_id, org_id, start_date, end_date)
