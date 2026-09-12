"""Autonomous financial advisor agent.

Uses the OpenAI Agents SDK (`agents` package, PyPI: `openai-agents`) when it
is installed and OPENAI_API_KEY is configured. Falls back to a deterministic,
rule-based analysis (no network calls) otherwise -- this keeps the app and
test suite fully runnable offline, and gives predictable output for tests.
"""
from app.agents import tools
from app.core.config import get_settings

try:  # pragma: no cover - exercised only when the SDK is installed
    from agents import Agent, Runner, function_tool

    _AGENTS_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AGENTS_SDK_AVAILABLE = False


AGENT_INSTRUCTIONS = (
    "You are an autonomous financial advisor for a small business. Use the "
    "provided tools to inspect the monthly report, the expense category "
    "breakdown, and recent transactions for the organization. Then: "
    "(1) identify the highest-cost expense categories and suggest concrete, "
    "actionable cost-reduction alternatives that do not sacrifice product "
    "quality, and (2) propose pricing or sales-volume adjustments that would "
    "increase throughput and profitability. Return a concise action_summary "
    "and structured insights."
)


def _rule_based_analysis(org_id: str, month: int, year: int) -> dict:
    """Deterministic analysis used when the Agents SDK / OpenAI API is not
    available (e.g. offline tests, no API key configured)."""
    report = tools.fetch_monthly_report(org_id=org_id, month=month, year=year)
    breakdown = tools.fetch_expense_breakdown(org_id=org_id, month=month, year=year)

    cost_reduction_suggestions = []
    for category in breakdown["top_cost_drivers"]:
        cost_reduction_suggestions.append(
            {
                "category": category,
                "suggestion": (
                    f"Negotiate bulk/volume discounts or alternate suppliers for "
                    f"'{category}' and audit for waste/overordering; consider "
                    f"substituting lower-cost inputs only where quality is unaffected."
                ),
            }
        )

    if report["is_profitable"]:
        pricing_suggestion = (
            "The business is profitable this period. Consider a modest volume "
            "push (e.g. bundling or loyalty discounts) to grow throughput while "
            "monitoring margin, rather than raising prices."
        )
    else:
        pricing_suggestion = (
            "The business operated at a loss this period. Consider a targeted "
            "price increase (3-7%) on top-selling items with low price "
            "sensitivity, paired with the cost-reduction actions above, to "
            "restore margin without materially harming volume."
        )

    insights = {
        "monthly_report": report,
        "expense_breakdown": breakdown,
        "cost_reduction_suggestions": cost_reduction_suggestions,
        "pricing_volume_suggestion": pricing_suggestion,
    }
    action_summary = (
        f"Analyzed {month}/{year} financials for org {org_id}: "
        f"net {'profit' if report['is_profitable'] else 'loss'} of "
        f"{abs(report['net_profit_loss'])}. Flagged top cost drivers "
        f"{breakdown['top_cost_drivers']} with reduction suggestions and "
        f"proposed a pricing/volume adjustment."
    )
    return {"action_summary": action_summary, "insights": insights}


def run_financial_advisor(org_id: str, month: int, year: int) -> dict:
    """Run the financial advisor agent for the given org/period.

    Returns {"action_summary": str, "insights": dict} regardless of whether
    the OpenAI Agents SDK is available, so callers (services/agent_service.py)
    have a stable contract to log into agent_logs.
    """
    settings = get_settings()
    if _AGENTS_SDK_AVAILABLE and settings.openai_api_key:  # pragma: no cover
        return _run_with_agents_sdk(org_id=org_id, month=month, year=year)
    return _rule_based_analysis(org_id=org_id, month=month, year=year)


def _run_with_agents_sdk(org_id: str, month: int, year: int) -> dict:  # pragma: no cover
    """Real OpenAI Agents SDK execution path (requires network + API key)."""
    from agents import Agent, Runner, function_tool

    @function_tool
    def get_monthly_report_tool(month: int, year: int) -> dict:
        """Fetch the monthly financial report for this organization."""
        return tools.fetch_monthly_report(org_id=org_id, month=month, year=year)

    @function_tool
    def get_expense_breakdown_tool(month: int, year: int) -> dict:
        """Fetch the expense category breakdown for this organization."""
        return tools.fetch_expense_breakdown(org_id=org_id, month=month, year=year)

    @function_tool
    def get_recent_transactions_tool(limit: int = 10) -> dict:
        """Fetch recent sales and expenses for this organization."""
        return tools.fetch_recent_transactions(org_id=org_id, limit=limit)

    agent = Agent(
        name="financial-advisor",
        instructions=AGENT_INSTRUCTIONS,
        tools=[get_monthly_report_tool, get_expense_breakdown_tool, get_recent_transactions_tool],
    )
    result = Runner.run_sync(
        agent, f"Analyze the financials for {month}/{year} and give recommendations."
    )
    insights = {"raw_output": result.final_output}
    action_summary = str(result.final_output)[:500]
    return {"action_summary": action_summary, "insights": insights}
