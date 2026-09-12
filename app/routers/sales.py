"""Sales endpoints. Delegates all logic to app.services.sales_service.

`org_id` always comes from the URL path (never the body) and is verified
against the authenticated user's ownership inside the service layer.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.core.security import CurrentUser, get_current_user
from app.models.sales import SaleCreate, SaleOut
from app.services import sales_service

router = APIRouter(prefix="/orgs/{org_id}/sales", tags=["sales"])


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def log_sale(
    org_id: str,
    payload: SaleCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return sales_service.log_sale(current_user.user_id, org_id, payload)


@router.get("", response_model=list[SaleOut])
def list_sales(
    org_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return sales_service.list_sales(current_user.user_id, org_id, start_date, end_date)
