from fastapi import APIRouter, Depends, status

from app.core.auth import CurrentUser, get_current_user
from app.schemas.sales import SaleCreate, SaleOut
from app.services import sales_service

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def create_sale(payload: SaleCreate, current_user: CurrentUser = Depends(get_current_user)):
    return sales_service.log_sale(
        org_id=current_user.org_id, user_id=current_user.user_id, payload=payload
    )


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return sales_service.get_sale(org_id=current_user.org_id, sale_id=sale_id)
