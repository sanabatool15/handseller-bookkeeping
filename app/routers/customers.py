from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.customers import Customer, CustomerCreate, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])
TABLE = "customers"


@router.get("", response_model=list[Customer])
def list_customers(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Customer, status_code=201)
def create_customer(payload: CustomerCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{customer_id}", response_model=Customer)
def get_customer(customer_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, customer_id)


@router.patch("/{customer_id}", response_model=Customer)
def update_customer(
    customer_id: str, payload: CustomerUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, customer_id, payload.model_dump(mode="json"))


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, customer_id)
