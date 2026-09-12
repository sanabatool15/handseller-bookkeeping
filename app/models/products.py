"""Products / inventory items sold by handsellers."""

from pydantic import BaseModel

from app.models.common import ORMBase


class ProductBase(BaseModel):
    name: str
    sku: str | None = None
    description: str | None = None
    unit_price: float
    unit_cost: float = 0.0
    quantity_on_hand: int = 0
    reorder_level: int = 0
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    description: str | None = None
    unit_price: float | None = None
    unit_cost: float | None = None
    quantity_on_hand: int | None = None
    reorder_level: int | None = None
    is_active: bool | None = None


class Product(ProductBase, ORMBase):
    pass


class InventoryAdjustment(BaseModel):
    """Used to increase/decrease stock (e.g. restock, correction, shrinkage)."""

    quantity_delta: int
    reason: str | None = None
