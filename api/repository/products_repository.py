"""Products repository (SQL Server / T-SQL). Every read/update/delete filters by id AND org_id in the same statement."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from core.db import Db
from repository.base import clamp_page

# products has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334).
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, created_by uniqueidentifier, "
    "name nvarchar(200), sku nvarchar(64), price decimal(14,2), stock_qty int, reorder_level int, "
    "is_active bit, created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.created_by, INSERTED.name, INSERTED.sku, INSERTED.price, "
    "INSERTED.stock_qty, INSERTED.reorder_level, INSERTED.is_active, INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_INSERT = (
    _OUT_DECL
    + "INSERT INTO products (org_id, created_by, name, sku, price, stock_qty, reorder_level) "
    + _OUT_COLS
    + "VALUES (?, ?, ?, ?, ?, ?, ?); SELECT * FROM @o;"
)
_LIST = (
    "SELECT * FROM products WHERE org_id = ? "
    "ORDER BY name, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_LIST_LOW_STOCK = (
    "SELECT * FROM products WHERE org_id = ? AND stock_qty <= reorder_level "
    "ORDER BY name, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_GET_SCOPED = "SELECT TOP (1) * FROM products WHERE id = ? AND org_id = ?"
# Updates never set a column to NULL (the service strips None values), so COALESCE(?, col) keeps the
# statement static. stock_qty is deliberately NOT updatable here: only adjust_stock changes it.
_UPDATE = (
    _OUT_DECL
    + "UPDATE products SET name = COALESCE(?, name), sku = COALESCE(?, sku), price = COALESCE(?, price), "
    + "reorder_level = COALESCE(?, reorder_level), is_active = COALESCE(?, is_active) "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
_DELETE = "DELETE FROM products WHERE id = ? AND org_id = ?"
# Race-safe: a single atomic statement. The row lock is held while the guard `stock_qty + ? >= 0` is
# evaluated, so concurrent decrements serialise and stock can never go negative. Zero rows => either the
# product is not in this org, or stock would go negative (the service tells them apart).
_ADJUST = (
    _OUT_DECL
    + "UPDATE products SET stock_qty = stock_qty + ? "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ? AND stock_qty + ? >= 0; SELECT * FROM @o;"
)
_UPDATABLE = ("name", "sku", "price", "reorder_level", "is_active")


def _money(amount: float) -> Decimal:
    return Decimal(str(round(float(amount), 2)))


def create_product(db: Db, *, org_id: str, created_by: str, name: str, sku: str, price: float, stock_qty: int, reorder_level: int) -> dict[str, Any]:
    row = db.query_one(_INSERT, (org_id, created_by, name, sku, _money(price), int(stock_qty), int(reorder_level)))
    if row is None:
        raise RuntimeError("Failed to create product")
    return row


def list_products(db: Db, *, org_id: str, limit: int = 100, offset: int = 0, low_stock: bool = False) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    return db.query(_LIST_LOW_STOCK if low_stock else _LIST, (org_id, offset, limit))


def get_product_scoped(db: Db, *, product_id: str, org_id: str) -> Optional[dict[str, Any]]:
    return db.query_one(_GET_SCOPED, (product_id, org_id))


def update_product_scoped(db: Db, *, product_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    unknown = set(updates) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    price = updates.get("price")
    active = updates.get("is_active")
    params = (
        updates.get("name"),
        updates.get("sku"),
        None if price is None else _money(price),
        updates.get("reorder_level"),
        None if active is None else int(bool(active)),
        product_id,
        org_id,
    )
    return db.query_one(_UPDATE, params)


def delete_product_scoped(db: Db, *, product_id: str, org_id: str) -> bool:
    return db.execute(_DELETE, (product_id, org_id)) > 0


def adjust_stock_scoped(db: Db, *, product_id: str, org_id: str, delta: int) -> Optional[dict[str, Any]]:
    """Atomically stock_qty += delta. Returns the updated row, or None when the product is not in this
    org OR the adjustment would make stock negative (callers distinguish with get_ownership)."""
    delta = int(delta)
    return db.query_one(_ADJUST, (delta, product_id, org_id, delta))
