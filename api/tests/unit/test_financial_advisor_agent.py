import pytest

from ai_agents.api.financial_advisor_agent import (
    AgentUnavailableError,
    BookkeepingResult,
    run_bookkeeping_agent,
    run_financial_advisor,
)


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
    summary = {"org_id": "org-1", "total_sales": 10.0, "total_expenses": 5.0, "net_profit": 5.0}
    try:
        advice = await run_financial_advisor(_FakeDb(), summary)
    except AgentUnavailableError:
        # Valid: SDK not installed, no API key, no network, or the live
        # call itself failed — the caller (the Inngest job step) falls
        # back to the rule-based engine in this case.
        return
    # Valid: the real SDK ran end-to-end and produced advice.
    assert isinstance(advice, str) and advice.strip()


class _FakeDb:
    """Minimal stand-in; the SDK-unavailable path never touches it."""


@pytest.mark.asyncio
async def test_run_bookkeeping_agent_unavailable_or_routes_correctly():
    """Section 9 of the design plan: routing correctness (which specialist
    handled a given input) is a testable dimension independent of whether
    the specialist's own output was any good. `last_agent`/`current_agent`
    on the run result is how that's checked.

    Same source-agnostic shape as the test above: either the SDK genuinely
    isn't usable here (AgentUnavailableError, and this test stops there),
    or it ran end-to-end and the returned `agent_name` names a real
    specialist ("Investigate agent" or "Record agent" — never the planner,
    since the planner's only action is a handoff, never a final answer).
    """
    try:
        outcome = await run_bookkeeping_agent(
            _FakeDb(),
            org_id="org-1",
            user_id="user-1",
            user_message="Why did we lose money this month?",
            fallback_summary={"total_sales": 10.0, "total_expenses": 20.0, "net_profit": -10.0},
        )
    except AgentUnavailableError:
        return

    assert outcome["agent_name"] in {"Investigate agent", "Record agent"}
    assert outcome["agent_name"] != "Planner agent"
    result = BookkeepingResult.model_validate(outcome["result"])
    assert result.mode in {"investigation", "record_entry"}


def test_bookkeeping_result_requires_valid_mode():
    """`BookkeepingResult.mode` is the field the eval harness (plan Section 9)
    asserts on directly instead of parsing prose — it must be constrained to
    the two known specialist outcomes."""
    with pytest.raises(Exception):
        BookkeepingResult(mode="something_else", summary="x")  # type: ignore[arg-type]

    investigation = BookkeepingResult(
        mode="investigation",
        summary="Expenses spiked in packaging.",
        root_cause="Packaging costs are 3x last month's average.",
        recommendation="Shop around for a cheaper packaging supplier.",
        used_web_search=True,
    )
    assert investigation.record_reference is None

    record_entry = BookkeepingResult(
        mode="record_entry",
        summary="Recorded a $40 packaging expense.",
        record_reference="https://app.handseller.example/orgs/org-1/expenses/exp-1",
    )
    assert record_entry.root_cause is None
