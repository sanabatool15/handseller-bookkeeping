from pydantic import BaseModel, Field


class MonthlyReport(BaseModel):
    month: int
    year: int
    total_sales: float
    total_expenses: float
    net_profit_loss: float
    is_profitable: bool


class CategoryBreakdown(BaseModel):
    category: str
    total_amount: float
    percentage_of_total: float


class ExpenseBreakdownReport(BaseModel):
    total_expenses: float
    breakdown: list[CategoryBreakdown]
    top_cost_drivers: list[str] = Field(
        description="Categories ranked highest-spend first, top 3 (or fewer)"
    )
