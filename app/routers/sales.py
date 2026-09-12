from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth import CurrentUser, get_current_user
from app.models.sales import Sale, SaleCreate, SaleUpdate
from app.services import sales_service

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=Sale, status_code=status.HTTP_201_CREATED)
def create_sale(
    payload: SaleCreate,
    current: CurrentUser = Depends(get_current_user),
) -> Sale:
    return sales_service.log_sale(current, payload)


@router.get("", response_model=list[Sale])
def list_sales(
    start: date | None = None,
    end: date | None = None,
    current: CurrentUser = Depends(get_current_user),
) -> list[Sale]:
    return sales_service.list_sales(current, start, end)


@router.get("/{sale_id}", response_model=Sale)
def get_sale(
    sale_id: UUID,
    current: CurrentUser = Depends(get_current_user),
) -> Sale:
    return sales_service.get_sale(current, sale_id)


@router.patch("/{sale_id}", response_model=Sale)
def update_sale(
    sale_id: UUID,
    payload: SaleUpdate,
    current: CurrentUser = Depends(get_current_user),
) -> Sale:
    return sales_service.update_sale(current, sale_id, payload)


@router.delete("/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sale(
    sale_id: UUID,
    current: CurrentUser = Depends(get_current_user),
) -> None:
    sales_service.delete_sale(current, sale_id)
