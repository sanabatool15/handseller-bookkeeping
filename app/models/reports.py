from pydantic import BaseModel, Field


class MonthlyReport(BaseModel):
    org_id: str
    year: int
    month: int = Field(ge=1, le=12)
    total_sales: float
    total_expenses: float
    net_profit: float
    sales_count: int
    expenses_count: int
