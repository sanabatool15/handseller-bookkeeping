"""Products & stock business logic + validation. No direct DB access here — only via repository."""
from __future__ import annotations

from typing import Any

from core.db import Db

from repository import base as repo_base
from repository import products_repository

# Keeps stock_qty (int, max 2,147,483,647) from overflowing in `stock_qty + delta`.
MAX_QTY = 1_000_000


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class DuplicateSkuError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


def _clean_text(value: str | None, field: str, max_len: int) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationError(f"Product {field} must not be empty")
    if len(text) > max_len:
        raise ValidationError(f"Product {field} must be at most {max_len} characters")
    return text


def _check_price(price: float) -> None:
    if price < 0:
        raise ValidationError("Product price must be >= 0")


def _check_qty(value: int, field: str) -> None:
    if value < 0:
        raise ValidationError(f"Product {field} must be >= 0")
    if value > MAX_QTY:
        raise ValidationError(f"Product {field} must be at most {MAX_QTY}")


def create_product(db: Db, *, org_id: str, user_id: str, name: str, sku: str, price: float, stock_qty: int = 0, reorder_level: int = 0) -> dict[str, Any]:
    name = _clean_text(name, "name", 200)
    sku = _clean_text(sku, "sku", 64)
    _check_price(price)
    _check_qty(stock_qty, "stock_qty")
    _check_qty(reorder_level, "reorder_level")
    try:
        return products_repository.create_product(
            db, org_id=org_id, created_by=user_id, name=name, sku=sku, price=price,
            stock_qty=stock_qty, reorder_level=reorder_level,
        )
    except repo_base.DuplicateRecordError as exc:
        raise DuplicateSkuError(f"SKU '{sku}' already exists") from exc


def list_products(db: Db, *, org_id: str, limit: int = 100, offset: int = 0, low_stock: bool = False) -> list[dict[str, Any]]:
    return products_repository.list_products(db, org_id=org_id, limit=limit, offset=offset, low_stock=low_stock)


def get_product(db: Db, *, org_id: str, product_id: str) -> dict[str, Any]:
    product = products_repository.get_product_scoped(db, product_id=product_id, org_id=org_id)
    if product is None:
        raise NotFoundError("Product not found")
    return product


def update_product(db: Db, *, org_id: str, product_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in updates.items() if v is not None}
    if "name" in clean:
        clean["name"] = _clean_text(clean["name"], "name", 200)
    if "sku" in clean:
        clean["sku"] = _clean_text(clean["sku"], "sku", 64)
    if "price" in clean:
        _check_price(clean["price"])
    if "reorder_level" in clean:
        _check_qty(clean["reorder_level"], "reorder_level")
    try:
        updated = products_repository.update_product_scoped(db, product_id=product_id, org_id=org_id, updates=clean)
    except repo_base.DuplicateRecordError as exc:
        raise DuplicateSkuError(f"SKU '{clean.get('sku')}' already exists") from exc
    if updated is None:
        raise NotFoundError("Product not found")
    return updated


def delete_product(db: Db, *, org_id: str, product_id: str) -> None:
    if not products_repository.delete_product_scoped(db, product_id=product_id, org_id=org_id):
        raise NotFoundError("Product not found")


def adjust_stock(db: Db, *, org_id: str, product_id: str, delta: int, reason: str | None = None) -> dict[str, Any]:
    """Add/remove stock atomically. `reason` is validated but not persisted yet (no stock-movement table; specs/17)."""
    if delta == 0:
        raise ValidationError("Stock delta must not be zero")
    if abs(delta) > MAX_QTY:
        raise ValidationError(f"Stock delta must be between -{MAX_QTY} and {MAX_QTY}")
    if reason is not None and len(reason) > 500:
        raise ValidationError("Reason must be at most 500 characters")
    updated = products_repository.adjust_stock_scoped(db, product_id=product_id, org_id=org_id, delta=delta)
    if updated is not None:
        return updated
    # Zero rows. The decision above was made by the single atomic UPDATE; this scoped existence check
    # (id AND org_id) only picks the error code: unknown/other-org => 404, otherwise stock would go negative => 409.
    if repo_base.get_ownership(db, table="products", record_id=product_id, org_id=org_id):
        raise InsufficientStockError("Insufficient stock for this adjustment")
    raise NotFoundError("Product not found")
