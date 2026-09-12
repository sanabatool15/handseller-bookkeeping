from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.sales import Sale, SaleCreate, SaleUpdate

router = APIRouter(prefix="/sales", tags=["sales"])
TABLE = "sales"


def _compute_total(items: list[dict]) -> float:
    return round(sum(item["quantity"] * item["unit_price"] for item in items), 2)


@router.get("", response_model=list[Sale])
def list_sales(limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Sale, status_code=201)
def create_sale(payload: SaleCreate, db: Client = Depends(get_supabase)):
    data = payload.model_dump(mode="json")
    data["total_amount"] = _compute_total(data["items"])
    return create_row(db, TABLE, data)


@router.get("/{sale_id}", response_model=Sale)
def get_sale(sale_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, sale_id)


@router.patch("/{sale_id}", response_model=Sale)
def update_sale(sale_id: str, payload: SaleUpdate, db: Client = Depends(get_supabase)):
    data = payload.model_dump(mode="json")
    if data.get("items"):
        data["total_amount"] = _compute_total(data["items"])
    return update_row(db, TABLE, sale_id, data)


@router.delete("/{sale_id}", status_code=204)
def delete_sale(sale_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, sale_id)
