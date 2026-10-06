"""Fast, network-free checks of financial_advisor_agent's SDK wiring.

Scope: this file ONLY tests ai_agents/api/financial_advisor_agent.py --
how it builds the Agent/Model objects and calls Runner.run_streamed. It does
not touch jobs/financial_agent_job.py (Inngest orchestration), Supabase, or
Redis -- those have their own separate test files.

Unlike test_financial_advisor_agent.py (which is deliberately
network-agnostic and passes whether or not a real call happens), this
module mocks agents.Runner.run_streamed so it can assert HOW the SDK is
invoked --- without needing `docker compose up`, a real OPENAI_API_KEY, or
network access. Run this after any change to financial_advisor_agent.py
instead of reaching for a live docker run every time.

Run with `-s` to see the printed narration of what each test checked:
    pytest tests/unit/test_financial_advisor_agent_wiring.py -v -s
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_agents.api.financial_advisor_agent import (
    AgentUnavailableError,
    BookkeepingResult,
    run_financial_advisor,
)

SUMMARY = {"org_id": "org-1", "total_sales": 10.0, "total_expenses": 5.0, "net_profit": 5.0}


class _FakeDb:
    """Minimal stand-in for a Supabase client; these tests mock the SDK
    layer above it and never touch it directly."""


class _FakeStreamResult:
    """Stands in for `RunResultStreaming`: `Runner.run_streamed(...)` returns
    this synchronously, then callers `async for event in .stream_events()`.
    """

    def __init__(self, *, final_output=None, last_agent=None, events=None, raise_immediately: Exception | None = None):
        self.final_output = final_output
        self.last_agent = last_agent
        self._events = events or []
        self._raise_immediately = raise_immediately

    async def stream_events(self):
        if self._raise_immediately is not None:
            raise self._raise_immediately
        for event in self._events:
            yield event


def _patched_agent_class():
    """A stand-in for `agents.Agent` that just remembers its kwargs and
    reports a distinct `.name` per instantiation, mirroring planner /
    investigate / record agents in build order."""
    names = iter(["Investigate agent", "Record agent", "Planner agent"])

    def _build(*a, **kw):
        kw.setdefault("handoff_description", None)
        kw["name"] = next(names)
        return SimpleNamespace(**kw)

    mock_agent_cls = MagicMock()
    mock_agent_cls.side_effect = _build
    return mock_agent_cls


@pytest.mark.asyncio
async def test_agent_model_is_never_a_bare_string_when_client_is_configured():
    """Regression test for the MultiProvider "Unknown prefix" bug: if a
    custom OpenAI-compatible client (e.g. OpenRouter) is configured,
    Agent(model=...) must receive an explicit Model object, never a bare
    string --- a bare string gets routed through agents' MultiProvider,
    which mis-parses any "/" in the model name (e.g. "inclusionai/foo")
    as an unrecognized provider prefix and raises UserError.
    """
    print("\n[TEST] agent model must not be a bare string when a custom OpenAI-compatible client is configured")
    fake_result = _FakeStreamResult(
        final_output=BookkeepingResult(mode="investigation", summary="some advice"),
        last_agent=SimpleNamespace(name="Investigate agent"),
    )
    mock_agent_cls = _patched_agent_class()

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run_streamed", return_value=fake_result) as mock_run, \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent", new=mock_agent_cls), \
         patch("ai_agents.api.financial_advisor_agent._sdk_handoff", side_effect=lambda a: a), \
         patch("ai_agents.api.financial_advisor_agent._openai_client", new=object()):
        print("  simulating: OPENAI_API_KEY + OPENAI_API_BASE_URL set (e.g. OpenRouter), Runner.run_streamed() mocked to succeed")
        advice = await run_financial_advisor(_FakeDb(), SUMMARY)

        assert mock_agent_cls.called, "Agent(...) was never constructed"
        for call in mock_agent_cls.call_args_list:
            model_arg = call.kwargs.get("model")
            print(f"  Agent(model=...) received: {type(model_arg).__name__}")
            assert not isinstance(model_arg, str), (
                "Agent(model=...) got a bare string while a custom client was "
                "configured --- this reintroduces the MultiProvider "
                "'Unknown prefix' bug. It must be an explicit "
                "OpenAIChatCompletionsModel instead."
            )
        mock_run.assert_called_once()
        assert advice.strip()
        print("  PASS: every Agent's model was an explicit Model object, not a bare string -- MultiProvider prefix bug did not reoccur")


@pytest.mark.asyncio
async def test_agent_constructor_never_receives_api_key_or_base_url():
    """Regression test for the earlier bug: real Agent.__init__() has no
    api_key/base_url kwargs at all --- passing them raises TypeError,
    which the job step swallows as a silent fallback. Custom endpoints
    must go through set_default_openai_client instead.
    """
    print("\n[TEST] Agent(...) constructor calls must never be given api_key/base_url kwargs")
    fake_result = _FakeStreamResult(
        final_output=BookkeepingResult(mode="investigation", summary="some advice"),
        last_agent=SimpleNamespace(name="Investigate agent"),
    )
    mock_agent_cls = _patched_agent_class()

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run_streamed", return_value=fake_result), \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent", new=mock_agent_cls), \
         patch("ai_agents.api.financial_advisor_agent._sdk_handoff", side_effect=lambda a: a):
        await run_financial_advisor(_FakeDb(), SUMMARY)

        for call in mock_agent_cls.call_args_list:
            kwargs = call.kwargs
            print(f"  Agent(...) was called with kwargs: {sorted(kwargs.keys())}")
            assert "api_key" not in kwargs
            assert "base_url" not in kwargs
        print("  PASS: no api_key/base_url kwargs passed on any of the three agents -- TypeError bug did not reoccur")


@pytest.mark.asyncio
async def test_runner_failure_raises_agent_unavailable_with_real_cause():
    """When Runner.run_streamed()'s event stream fails (network, auth,
    whatever), the raised AgentUnavailableError must include the real
    exception's type/message --- this is the fix for "why did it silently
    fall back with no error visible anywhere."
    """
    print("\n[TEST] a real Runner.run_streamed() failure must surface its type+message inside AgentUnavailableError")
    fake_result = _FakeStreamResult(raise_immediately=ConnectionError("Name or service not known"))
    mock_agent_cls = _patched_agent_class()

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run_streamed", return_value=fake_result), \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent", new=mock_agent_cls), \
         patch("ai_agents.api.financial_advisor_agent._sdk_handoff", side_effect=lambda a: a):
        print("  simulating: stream_events() raises ConnectionError('Name or service not known') (DNS failure, as seen in real logs)")
        with pytest.raises(AgentUnavailableError) as exc_info:
            await run_financial_advisor(_FakeDb(), SUMMARY)

        message = str(exc_info.value)
        print(f"  AgentUnavailableError message raised: {message!r}")
        assert "ConnectionError" in message
        assert "Name or service not known" in message
        print("  PASS: real exception type + message are visible, not silently swallowed")


@pytest.mark.asyncio
async def test_empty_final_output_raises_agent_unavailable():
    print("\n[TEST] Runner.run_streamed() succeeding with no final_output must still raise AgentUnavailableError, not return empty advice")
    fake_result = _FakeStreamResult(final_output=None, last_agent=SimpleNamespace(name="Investigate agent"))
    mock_agent_cls = _patched_agent_class()

    with patch("ai_agents.api.financial_advisor_agent._SdkRunner.run_streamed", return_value=fake_result), \
         patch("ai_agents.api.financial_advisor_agent._SdkAgent", new=mock_agent_cls), \
         patch("ai_agents.api.financial_advisor_agent._sdk_handoff", side_effect=lambda a: a):
        with pytest.raises(AgentUnavailableError):
            await run_financial_advisor(_FakeDb(), SUMMARY)
        print("  PASS: empty output correctly triggers AgentUnavailableError -> caller falls back to rule-based advice")
