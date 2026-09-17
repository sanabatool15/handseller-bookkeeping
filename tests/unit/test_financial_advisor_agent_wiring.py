"""Fast, network-free checks of financial_advisor_agent's SDK wiring.

Unlike test_financial_advisor_agent.py (which is deliberately
network-agnostic and passes whether or not a real call happens), this
module mocks agents.Runner.run so it can assert HOW the SDK is invoked
--- without needing `docker compose up`, a real OPENAI_API_KEY, or network
access. Run this after any change to financial_advisor_agent.py instead of
reaching for a live docker run every time.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_agents.api.financial_advisor_agent import AgentUnavailableError, run_financial_advisor


SUMMARY = {"total_sales": 10.0, "total_expenses": 5.0, "net_profit": 5.0}


@pytest.mark.asyncio
async def test_agent_model_is_never_a_bare_string_when_client_is_configured():
    """Regression test for the MultiProvider "Unknown prefix" bug: if a
    custom OpenAI-compatible client (e.g. OpenRouter) is configured,
    Agent(model=...) must receive an explicit Model object, never a bare
    string --- a bare string gets routed through agents' MultiProvider,
    which mis-parses any "/" in the model name (e.g. "inclusionai/foo")
    as an unrecognized provider prefix and raises UserError.
    """
    fake_result = SimpleNamespace(final_output="some advice")

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run", new=AsyncMock(return_value=fake_result)) as mock_run, \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent") as mock_agent_cls, \
         patch("ai_agents.api.financial_advisor_agent._openai_client", new=object()):
        mock_agent_cls.return_value = SimpleNamespace(name="FinancialAdvisor")

        await run_financial_advisor(SUMMARY)

        assert mock_agent_cls.called, "Agent(...) was never constructed"
        _, kwargs = mock_agent_cls.call_args
        assert not isinstance(kwargs.get("model"), str), (
            "Agent(model=...) got a bare string while a custom client was "
            "configured --- this reintroduces the MultiProvider "
            "'Unknown prefix' bug. It must be an explicit "
            "OpenAIChatCompletionsModel instead."
        )
        mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_constructor_never_receives_api_key_or_base_url():
    """Regression test for the earlier bug: real Agent.__init__() has no
    api_key/base_url kwargs at all --- passing them raises TypeError,
    which the job step swallows as a silent fallback. Custom endpoints
    must go through set_default_openai_client instead.
    """
    fake_result = SimpleNamespace(final_output="some advice")

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run", new=AsyncMock(return_value=fake_result)), \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent") as mock_agent_cls:
        mock_agent_cls.return_value = SimpleNamespace(name="FinancialAdvisor")

        await run_financial_advisor(SUMMARY)

        _, kwargs = mock_agent_cls.call_args
        assert "api_key" not in kwargs
        assert "base_url" not in kwargs


@pytest.mark.asyncio
async def test_runner_failure_raises_agent_unavailable_with_real_cause():
    """When Runner.run() fails (network, auth, whatever), the raised
    AgentUnavailableError must include the real exception's type/message
    --- this is the fix for "why did it silently fall back with no error
    visible anywhere."
    """
    with patch(
        "ai_agents.api.financial_advisor_agent._SdkRunner.run",
        new=AsyncMock(side_effect=ConnectionError("Name or service not known")),
    ), patch("ai_agents.api.financial_advisor_agent._SdkAgent") as mock_agent_cls:
        mock_agent_cls.return_value = SimpleNamespace(name="FinancialAdvisor")

        with pytest.raises(AgentUnavailableError) as exc_info:
            await run_financial_advisor(SUMMARY)

        message = str(exc_info.value)
        assert "ConnectionError" in message
        assert "Name or service not known" in message


@pytest.mark.asyncio
async def test_empty_final_output_raises_agent_unavailable():
    fake_result = SimpleNamespace(final_output=None)

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run", new=AsyncMock(return_value=fake_result)), \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent") as mock_agent_cls:
        mock_agent_cls.return_value = SimpleNamespace(name="FinancialAdvisor")

        with pytest.raises(AgentUnavailableError):
            await run_financial_advisor(SUMMARY)
