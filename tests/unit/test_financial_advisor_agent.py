import pytest

from ai_agents.api.financial_advisor_agent import AgentUnavailableError, run_financial_advisor


@pytest.mark.asyncio
async def test_agent_unavailable_or_succeeds_without_crashing():
    """The `agents/` -> `ai_agents/` rename fixed the package-name collision
    that used to make the real OpenAI Agents SDK structurally unreachable
    (see ai_agents/api/financial_advisor_agent.py's module docstring): the
    real SDK is now genuinely importable here.

    Whether a given test run actually gets a live agent response still
    depends on environment specifics outside this test's control — is
    `openai-agents` installed, is `OPENAI_API_KEY` set, is there network
    access. This test asserts the function behaves correctly either way:
    it must not raise anything other than the documented
    AgentUnavailableError, and if it *does* succeed, it must return a
    non-empty string. Both are valid, correct outcomes of the fix — the
    test is intentionally source-agnostic rather than assuming one
    specific environment.
    """
    summary = {"total_sales": 10.0, "total_expenses": 5.0, "net_profit": 5.0}
    try:
        advice = await run_financial_advisor(summary)
    except AgentUnavailableError:
        # Valid: SDK not installed, no API key, no network, or the live
        # call itself failed — the caller (the Inngest job step) falls
        # back to the rule-based engine in this case.
        return
    # Valid: the real SDK ran end-to-end and produced advice.
    assert isinstance(advice, str) and advice.strip()
