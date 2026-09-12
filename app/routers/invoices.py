from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.invoices import Invoice, InvoiceCreate, InvoiceUpdate

router = APIRouter(prefix="/invoices", tags=["invoices"])
TABLE = "invoices"


@router.get("", response_model=list[Invoice])
def list_invoices(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Invoice, status_code=201)
def create_invoice(payload: InvoiceCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, invoice_id)


@router.patch("/{invoice_id}", response_model=Invoice)
def update_invoice(
    invoice_id: str, payload: InvoiceUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, invoice_id, payload.model_dump(mode="json"))


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, invoice_id)
