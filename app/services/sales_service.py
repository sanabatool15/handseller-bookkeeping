"""Business logic for sales. Delegates all DB access to the repository layer."""
from datetime import date

from app.models.sales import SaleCreate, SaleOut
from app.services.ownership_service import assert_owns_org
from app.repository import sales_repo


def log_sale(user_id: str, org_id: str, payload: SaleCreate) -> SaleOut:
    """Logs a sale for `org_id`, after verifying `user_id` owns it."""
    assert_owns_org(user_id, org_id)
    sale_date = payload.sale_date or date.today()
    row = sales_repo.create_sale(
        org_id=org_id,
        amount=payload.amount,
        voucher_reference=payload.voucher_reference,
        sale_date=sale_date,
    )
    return SaleOut(**row)


def list_sales(
    user_id: str, org_id: str, start_date: date | None = None, end_date: date | None = None
) -> list[SaleOut]:
    assert_owns_org(user_id, org_id)
    rows = sales_repo.list_sales_for_org(org_id, start_date, end_date)
    return [SaleOut(**row) for row in rows]
