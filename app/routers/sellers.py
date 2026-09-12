from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.sellers import Seller, SellerCreate, SellerUpdate

router = APIRouter(prefix="/sellers", tags=["sellers"])
TABLE = "sellers"


@router.get("", response_model=list[Seller])
def list_sellers(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Seller, status_code=201)
def create_seller(payload: SellerCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{seller_id}", response_model=Seller)
def get_seller(seller_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, seller_id)


@router.patch("/{seller_id}", response_model=Seller)
def update_seller(
    seller_id: str, payload: SellerUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, seller_id, payload.model_dump(mode="json"))


@router.delete("/{seller_id}", status_code=204)
def delete_seller(seller_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, seller_id)
