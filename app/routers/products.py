from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.products import (
    InventoryAdjustment,
    Product,
    ProductCreate,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["products"])
TABLE = "products"


@router.get("", response_model=list[Product])
def list_products(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Product, status_code=201)
def create_product(payload: ProductCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, product_id)


@router.patch("/{product_id}", response_model=Product)
def update_product(
    product_id: str, payload: ProductUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, product_id, payload.model_dump(mode="json"))


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, product_id)


@router.post("/{product_id}/adjust-inventory", response_model=Product)
def adjust_inventory(
    product_id: str,
    adjustment: InventoryAdjustment,
    db: Client = Depends(get_supabase),
):
    """Increase or decrease quantity_on_hand for a product (restock, shrinkage, etc.)."""
    product = get_row(db, TABLE, product_id)
    new_quantity = product["quantity_on_hand"] + adjustment.quantity_delta
    if new_quantity < 0:
        new_quantity = 0
    return update_row(db, TABLE, product_id, {"quantity_on_hand": new_quantity})
