import pytest

from agents.api.financial_advisor_agent import AgentUnavailableError, run_financial_advisor


@pytest.mark.asyncio
async def test_agent_unavailable_raises_documented_error():
    """In this repo, `agents/api/financial_advisor_agent.py` always finds the
    OpenAI Agents SDK import shadowed by the local `agents` package (see the
    module's docstring) — so it must raise AgentUnavailableError rather than
    silently doing nothing, letting callers fall back to the rule engine."""
    with pytest.raises(AgentUnavailableError):
        await run_financial_advisor({"total_sales": 10.0, "total_expenses": 5.0, "net_profit": 5.0})
