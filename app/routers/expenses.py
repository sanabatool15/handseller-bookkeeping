from fastapi import APIRouter, Depends, status

from app.core.auth import CurrentUser, get_current_user
from app.schemas.expenses import ExpenseCreate, ExpenseOut
from app.services import expenses_service

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate, current_user: CurrentUser = Depends(get_current_user)):
    return expenses_service.log_expense(
        org_id=current_user.org_id, user_id=current_user.user_id, payload=payload
    )


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return expenses_service.get_expense(org_id=current_user.org_id, expense_id=expense_id)
