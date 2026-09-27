from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.security import CurrentUser
from routers.deps import get_current_user, get_db
from services import expenses_service

router = APIRouter(prefix="/expenses", tags=["expenses"])


class ExpenseCreate(BaseModel):
    amount: float
    category: str = "general"
    voucher_reference: str | None = None
    description: str | None = None


class ExpenseUpdate(BaseModel):
    amount: float | None = None
    category: str | None = None
    voucher_reference: str | None = None
    description: str | None = None


@router.post("", status_code=201)
def create_expense(payload: ExpenseCreate, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return expenses_service.create_expense(
            db, org_id=user.org_id, user_id=user.user_id, amount=payload.amount,
            category=payload.category, voucher_reference=payload.voucher_reference, description=payload.description,
        )
    except expenses_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_expenses(limit: int = 100, offset: int = 0, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    return expenses_service.list_expenses(db, org_id=user.org_id, limit=limit, offset=offset)


@router.get("/{expense_id}")
def get_expense(expense_id: str, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return expenses_service.get_expense(db, org_id=user.org_id, expense_id=expense_id)
    except expenses_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{expense_id}")
def update_expense(expense_id: str, payload: ExpenseUpdate, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return expenses_service.update_expense(db, org_id=user.org_id, expense_id=expense_id, updates=payload.model_dump())
    except expenses_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except expenses_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: str, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        expenses_service.delete_expense(db, org_id=user.org_id, expense_id=expense_id)
    except expenses_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
