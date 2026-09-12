"""Business logic for sales. Delegates all persistence to repository/."""
from fastapi import HTTPException, status

from app.repository import sales_repository
from app.schemas.sales import SaleCreate


def log_sale(org_id: str, user_id: str, payload: SaleCreate) -> dict:
    return sales_repository.create_sale(
        org_id=org_id,
        user_id=user_id,
        amount=payload.amount,
        sale_date=payload.sale_date.isoformat(),
        voucher_reference=payload.voucher_reference,
    )


def get_sale(org_id: str, sale_id: str) -> dict:
    sale = sales_repository.get_sale_scoped(sale_id=sale_id, org_id=org_id)
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return sale
