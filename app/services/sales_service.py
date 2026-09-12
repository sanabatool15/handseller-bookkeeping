"""Business logic for sales. Delegates all persistence to
app.repository.sales_repository."""

from uuid import UUID

from fastapi import HTTPException, status

from app.auth import CurrentUser
from app.models.sales import Sale, SaleCreate, SaleUpdate
from app.repository import sales_repository


def log_sale(current: CurrentUser, payload: SaleCreate) -> Sale:
    data = payload.model_dump(mode="json")
    created = sales_repository.create_sale(current.org_id, current.user_id, data)
    return Sale.model_validate(created)


def list_sales(current: CurrentUser, start=None, end=None) -> list[Sale]:
    rows = sales_repository.list_sales_for_org(current.org_id, start, end)
    return [Sale.model_validate(row) for row in rows]


def get_sale(current: CurrentUser, sale_id: UUID) -> Sale:
    row = sales_repository.get_sale_by_id(sale_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if str(row["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this sale")
    return Sale.model_validate(row)


def update_sale(current: CurrentUser, sale_id: UUID, payload: SaleUpdate) -> Sale:
    existing = sales_repository.get_sale_by_id(sale_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if str(existing["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to modify this sale")

    updates = payload.model_dump(mode="json", exclude_unset=True)
    if not updates:
        return Sale.model_validate(existing)

    updated = sales_repository.update_sale(sale_id, current.org_id, updates)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return Sale.model_validate(updated)


def delete_sale(current: CurrentUser, sale_id: UUID) -> None:
    existing = sales_repository.get_sale_by_id(sale_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if str(existing["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to delete this sale")

    deleted = sales_repository.delete_sale(sale_id, current.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
