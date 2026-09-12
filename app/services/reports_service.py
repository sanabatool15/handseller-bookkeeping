"""Analytics and reporting business logic.

Both operations verify ownership before reading any data, then perform all
aggregation in-process over rows fetched from the repository layer (which
itself performs no aggregation — only plain reads).
"""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.core.exceptions import ValidationAppError
from app.models.reports import (
    ExpenseAnalytics,
    ExpenseCategoryBreakdown,
    MonthlyReport,
)
from app.repository import expenses_repo, sales_repo
from app.services.ownership_service import assert_owns_org


def _parse_month(month: str) -> tuple[date, date]:
    """Parses 'YYYY-MM' into (first_day, last_day) of that month."""
    try:
        year_str, month_str = month.split("-")
        year, month_num = int(year_str), int(month_str)
        if not 1 <= month_num <= 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValidationAppError(
            f"Invalid 'month' value [{month}]. Expected format YYYY-MM, e.g. 2025-01."
        ) from exc

    first_day = date(year, month_num, 1)
    last_day = date(year, month_num, calendar.monthrange(year, month_num)[1])
    return first_day, last_day


def get_monthly_report(user_id: str, org_id: str, month: str) -> MonthlyReport:
    assert_owns_org(user_id, org_id)
    start_date, end_date = _parse_month(month)

    sales = sales_repo.list_sales_for_org(org_id, start_date, end_date)
    expenses = expenses_repo.list_expenses_for_org(org_id, start_date, end_date)

    total_sales = sum((Decimal(str(s["amount"])) for s in sales), Decimal("0"))
    total_expenses = sum((Decimal(str(e["amount"])) for e in expenses), Decimal("0"))
    net_profit = total_sales - total_expenses

    return MonthlyReport(
        org_id=org_id,
        month=month,
        total_sales=total_sales,
        total_expenses=total_expenses,
        net_profit=net_profit,
        sales_count=len(sales),
        expenses_count=len(expenses),
    )


def get_expense_analytics(
    user_id: str,
    org_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ExpenseAnalytics:
    """Aggregates expenses by category to surface where money is going."""
    assert_owns_org(user_id, org_id)
    expenses = expenses_repo.list_expenses_for_org(org_id, start_date, end_date)

    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: dict[str, int] = defaultdict(int)
    for e in expenses:
        category = e["category"]
        totals[category] += Decimal(str(e["amount"]))
        counts[category] += 1

    grand_total = sum(totals.values(), Decimal("0"))

    breakdown = []
    for category, amount in totals.items():
        pct = (amount / grand_total * 100) if grand_total > 0 else Decimal("0")
        breakdown.append(
            ExpenseCategoryBreakdown(
                category=category,
                total_amount=amount,
                expense_count=counts[category],
                percentage_of_total=round(pct, 2),
            )
        )

    breakdown.sort(key=lambda item: item.total_amount, reverse=True)
    top_category = breakdown[0].category if breakdown else None

    return ExpenseAnalytics(
        org_id=org_id,
        total_expenses=grand_total,
        categories=breakdown,
        top_category=top_category,
    )
