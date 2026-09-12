"""Business logic / analytics for financial reports."""
import calendar

from app.repository import expenses_repository, sales_repository
from app.schemas.reports import CategoryBreakdown, ExpenseBreakdownReport, MonthlyReport


def _month_bounds(month: int, year: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    return start, end


def get_monthly_report(org_id: str, month: int, year: int) -> MonthlyReport:
    start, end = _month_bounds(month, year)
    sales = sales_repository.list_sales_for_period(org_id=org_id, start_date=start, end_date=end)
    expenses = expenses_repository.list_expenses_for_period(
        org_id=org_id, start_date=start, end_date=end
    )

    total_sales = round(sum(float(s["amount"]) for s in sales), 2)
    total_expenses = round(sum(float(e["amount"]) for e in expenses), 2)
    net = round(total_sales - total_expenses, 2)

    return MonthlyReport(
        month=month,
        year=year,
        total_sales=total_sales,
        total_expenses=total_expenses,
        net_profit_loss=net,
        is_profitable=net >= 0,
    )


def get_expense_breakdown(org_id: str, month: int, year: int) -> ExpenseBreakdownReport:
    start, end = _month_bounds(month, year)
    expenses = expenses_repository.list_expenses_for_period(
        org_id=org_id, start_date=start, end_date=end
    )

    totals_by_category: dict[str, float] = {}
    for e in expenses:
        category = e["category"]
        totals_by_category[category] = totals_by_category.get(category, 0.0) + float(e["amount"])

    total_expenses = round(sum(totals_by_category.values()), 2)

    breakdown = []
    for category, amount in totals_by_category.items():
        pct = round((amount / total_expenses) * 100, 2) if total_expenses > 0 else 0.0
        breakdown.append(
            CategoryBreakdown(category=category, total_amount=round(amount, 2), percentage_of_total=pct)
        )

    breakdown.sort(key=lambda c: c.total_amount, reverse=True)
    top_cost_drivers = [c.category for c in breakdown[:3]]

    return ExpenseBreakdownReport(
        total_expenses=total_expenses,
        breakdown=breakdown,
        top_cost_drivers=top_cost_drivers,
    )
