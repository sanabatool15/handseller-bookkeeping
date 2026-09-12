from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.payments import Payment, PaymentCreate, PaymentUpdate

router = APIRouter(prefix="/payments", tags=["payments"])
TABLE = "payments"


@router.get("", response_model=list[Payment])
def list_payments(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Payment, status_code=201)
def create_payment(payload: PaymentCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{payment_id}", response_model=Payment)
def get_payment(payment_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, payment_id)


@router.patch("/{payment_id}", response_model=Payment)
def update_payment(
    payment_id: str, payload: PaymentUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, payment_id, payload.model_dump(mode="json"))


@router.delete("/{payment_id}", status_code=204)
def delete_payment(payment_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, payment_id)
