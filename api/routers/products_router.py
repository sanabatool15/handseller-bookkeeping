from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.db import Db

from core.security import CurrentUser
from routers.deps import get_current_user, get_db
from services import products_service

router = APIRouter(prefix="/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str
    sku: str
    price: float
    stock_qty: int = 0
    reorder_level: int = 0


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    price: float | None = None
    reorder_level: int | None = None
    is_active: bool | None = None


class StockAdjustment(BaseModel):
    delta: int
    reason: str | None = None


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, products_service.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (products_service.DuplicateSkuError, products_service.InsufficientStockError, products_service.ProductInUseError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_DOMAIN_ERRORS = (
    products_service.ValidationError,
    products_service.NotFoundError,
    products_service.DuplicateSkuError,
    products_service.InsufficientStockError,
    products_service.ProductInUseError,
)


@router.post("", status_code=201)
def create_product(payload: ProductCreate, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    try:
        return products_service.create_product(
            db, org_id=user.org_id, user_id=user.user_id, name=payload.name, sku=payload.sku,
            price=payload.price, stock_qty=payload.stock_qty, reorder_level=payload.reorder_level,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("")
def list_products(limit: int = 100, offset: int = 0, low_stock: bool = False, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    return products_service.list_products(db, org_id=user.org_id, limit=limit, offset=offset, low_stock=low_stock)


@router.get("/{product_id}")
def get_product(product_id: str, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    try:
        return products_service.get_product(db, org_id=user.org_id, product_id=product_id)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.put("/{product_id}")
def update_product(product_id: str, payload: ProductUpdate, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    try:
        return products_service.update_product(db, org_id=user.org_id, product_id=product_id, updates=payload.model_dump())
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: str, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    try:
        products_service.delete_product(db, org_id=user.org_id, product_id=product_id)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/{product_id}/adjust-stock")
def adjust_stock(product_id: str, payload: StockAdjustment, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    try:
        return products_service.adjust_stock(db, org_id=user.org_id, product_id=product_id, delta=payload.delta, reason=payload.reason)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc
