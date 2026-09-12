"""Simple bookkeeping summary endpoints (income vs. expenses, seller totals)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.core.supabase_client import get_supabase

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary")
def profit_summary(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Client = Depends(get_supabase),
):
    """Total sales revenue, total expenses, and net profit for a date range."""
    sales_query = db.table("sales").select("total_amount, sale_date")
    expenses_query = db.table("expenses").select("amount, expense_date")

    if start_date:
        sales_query = sales_query.gte("sale_date", start_date.isoformat())
        expenses_query = expenses_query.gte("expense_date", start_date.isoformat())
    if end_date:
        sales_query = sales_query.lte("sale_date", end_date.isoformat())
        expenses_query = expenses_query.lte("expense_date", end_date.isoformat())

    sales = sales_query.execute().data or []
    expenses = expenses_query.execute().data or []

    total_revenue = round(sum(s["total_amount"] for s in sales), 2)
    total_expenses = round(sum(e["amount"] for e in expenses), 2)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": round(total_revenue - total_expenses, 2),
        "sale_count": len(sales),
        "expense_count": len(expenses),
    }


@router.get("/sellers/{seller_id}/performance")
def seller_performance(seller_id: str, db: Client = Depends(get_supabase)):
    """Total sales and commission earned for one seller."""
    seller_result = (
        db.table("sellers").select("*").eq("id", seller_id).limit(1).execute()
    )
    if not seller_result.data:
        return {"error": "seller not found"}
    seller = seller_result.data[0]

    sales = (
        db.table("sales")
        .select("total_amount")
        .eq("seller_id", seller_id)
        .execute()
        .data
        or []
    )
    total_sales = round(sum(s["total_amount"] for s in sales), 2)
    commission_owed = round(total_sales * seller.get("commission_rate", 0), 2)

    return {
        "seller_id": seller_id,
        "seller_name": seller.get("full_name"),
        "sale_count": len(sales),
        "total_sales": total_sales,
        "commission_rate": seller.get("commission_rate", 0),
        "commission_owed": commission_owed,
    }
