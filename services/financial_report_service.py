"""Aggregation helpers shared by the MCP ledger resource and the agent tools."""
from __future__ import annotations

import csv
import io
from typing import Any

from supabase import Client

from repository import expenses_repository, sales_repository


def monthly_summary(db: Client, *, org_id: str, year: int, month: int) -> dict[str, Any]:
    total_sales = sales_repository.sum_sales_for_month(db, org_id=org_id, year=year, month=month)
    total_expenses = expenses_repository.sum_expenses_for_month(db, org_id=org_id, year=year, month=month)
    return {
        "org_id": org_id,
        "year": year,
        "month": month,
        "total_sales": total_sales,
        "total_expenses": total_expenses,
        "net_profit": round(total_sales - total_expenses, 2),
    }


def monthly_ledger_csv(db: Client, *, org_id: str, year: int, month: int) -> str:
    """Builds the raw CSV text served by the ledger://{org_id}/monthly.csv MCP resource."""
    sales = sales_repository.list_sales(db, org_id=org_id, limit=1000)
    expenses = expenses_repository.list_expenses(db, org_id=org_id, limit=1000)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["type", "date", "amount", "category", "reference_or_customer", "description"])
    for s in sales:
        if not str(s.get("sale_date", "")).startswith(f"{year:04d}-{month:02d}"):
            continue
        writer.writerow(["sale", s.get("sale_date"), s.get("amount"), s.get("category"), s.get("customer_name"), s.get("description")])
    for e in expenses:
        if not str(e.get("expense_date", "")).startswith(f"{year:04d}-{month:02d}"):
            continue
        writer.writerow(["expense", e.get("expense_date"), e.get("amount"), e.get("category"), e.get("voucher_reference"), e.get("description")])
    return buf.getvalue()
