"""Business logic for expenses. Delegates all DB access to the repository layer."""
from datetime import date

from app.models.expenses import ExpenseCreate, ExpenseOut
from app.services.ownership_service import assert_owns_org
from app.repository import expenses_repo


def log_expense(user_id: str, org_id: str, payload: ExpenseCreate) -> ExpenseOut:
    """Logs an expense for `org_id`, after verifying `user_id` owns it."""
    assert_owns_org(user_id, org_id)
    expense_date = payload.expense_date or date.today()
    row = expenses_repo.create_expense(
        org_id=org_id,
        amount=payload.amount,
        category=payload.category,
        expense_date=expense_date,
    )
    return ExpenseOut(**row)


def list_expenses(
    user_id: str, org_id: str, start_date: date | None = None, end_date: date | None = None
) -> list[ExpenseOut]:
    assert_owns_org(user_id, org_id)
    rows = expenses_repo.list_expenses_for_org(org_id, start_date, end_date)
    return [ExpenseOut(**row) for row in rows]
