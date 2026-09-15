from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.security import CurrentUser
from routers.deps import get_current_user, get_db
from services import sales_service

router = APIRouter(prefix="/sales", tags=["sales"])


class SaleCreate(BaseModel):
    amount: float
    category: str = "general"
    description: str | None = None
    customer_name: str | None = None


class SaleUpdate(BaseModel):
    amount: float | None = None
    category: str | None = None
    description: str | None = None
    customer_name: str | None = None


@router.post("", status_code=201)
def create_sale(payload: SaleCreate, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return sales_service.create_sale(
            db, org_id=user.org_id, user_id=user.user_id, amount=payload.amount,
            category=payload.category, description=payload.description, customer_name=payload.customer_name,
        )
    except sales_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_sales(limit: int = 100, offset: int = 0, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    return sales_service.list_sales(db, org_id=user.org_id, limit=limit, offset=offset)


@router.get("/{sale_id}")
def get_sale(sale_id: str, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return sales_service.get_sale(db, org_id=user.org_id, sale_id=sale_id)
    except sales_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{sale_id}")
def update_sale(sale_id: str, payload: SaleUpdate, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        return sales_service.update_sale(db, org_id=user.org_id, sale_id=sale_id, updates=payload.model_dump())
    except sales_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except sales_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{sale_id}", status_code=204)
def delete_sale(sale_id: str, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    try:
        sales_service.delete_sale(db, org_id=user.org_id, sale_id=sale_id)
    except sales_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
