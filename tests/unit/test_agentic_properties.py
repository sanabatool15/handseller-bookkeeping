"""Property-based tests for the agentic part of this app: the fallback
rule engine, the deep-link tool, and the agent's failure-visibility/logging
behavior (ai_agents/ + the run_agent step in jobs/financial_agent_job.py).

Unlike the example-based tests in test_financial_advisor_agent_wiring.py
(fixed inputs, fixed mocked exceptions), these use Hypothesis to generate
hundreds of varied inputs per run and assert invariants that must hold for
ALL of them -- e.g. "the fallback engine never crashes, no matter what
numbers it's given" and "a failed agent call always produces a log entry
that says WHY it failed, never a silent/empty one."

Run:
    pytest tests/unit/test_agentic_properties.py -v
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from ai_agents.rules.fallback_engine import rule_based_financial_advice
from ai_agents.tools.deep_link import APP_BASE_URL, build_deep_link
from ai_agents.api.financial_advisor_agent import run_financial_advisor
from jobs.financial_agent_job import _step_run_agent


# ---------------------------------------------------------------------------
# Property 1: the offline rule-based fallback must NEVER crash and must
# ALWAYS produce non-empty, deterministic advice -- this is the one thing
# that is supposed to work no matter how broken the AI agent path is.
# ---------------------------------------------------------------------------

money = st.floats(
    min_value=-1_000_000, max_value=1_000_000, allow_nan=False, allow_infinity=False
)


@given(
    total_sales=money,
    total_expenses=money,
    include_net_profit=st.booleans(),
)
@settings(max_examples=100)
def test_fallback_engine_never_crashes_and_always_returns_advice(
    total_sales: float, total_expenses: float, include_net_profit: bool
):
    summary: dict[str, Any] = {"total_sales": total_sales, "total_expenses": total_expenses}
    if include_net_profit:
        summary["net_profit"] = total_sales - total_expenses

    advice = rule_based_financial_advice(summary)

    assert isinstance(advice, str)
    assert advice.strip(), "fallback engine must never return empty advice"
    assert "Month summary" in advice
    assert "rule-based fallback" in advice.lower()


@given(total_sales=money, total_expenses=money)
@settings(max_examples=50)
def test_fallback_engine_is_deterministic(total_sales: float, total_expenses: float):
    """Same input -> same output, every time. This matters because a user
    could poll the same completed job repeatedly and must see stable advice.
    """
    summary = {"total_sales": total_sales, "total_expenses": total_expenses}
    first = rule_based_financial_advice(summary)
    second = rule_based_financial_advice(dict(summary))
    assert first == second


@given(st.dictionaries(st.text(min_size=1, max_size=20), st.integers()))
@settings(max_examples=50)
def test_fallback_engine_tolerates_missing_or_extra_keys(garbage: dict[str, Any]):
    """The real summary dict shape can drift (a new field added upstream,
    a field missing due to a partial query failure). The fallback engine
    must degrade gracefully (treat missing numbers as 0), never KeyError.
    """
    advice = rule_based_financial_advice(garbage)
    assert isinstance(advice, str) and advice.strip()


# ---------------------------------------------------------------------------
# Property 2: build_deep_link must always produce a well-formed, safe URL
# for any org_id/resource/resource_id/query combination an agent tool call
# might pass it.
# ---------------------------------------------------------------------------

safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), min_codepoint=48, max_codepoint=122),
    min_size=1,
    max_size=20,
)


@given(
    org_id=safe_text,
    resource=safe_text,
    resource_id=st.one_of(st.none(), safe_text),
)
@settings(max_examples=50)
def test_deep_link_always_well_formed(org_id: str, resource: str, resource_id: str | None):
    link = build_deep_link(org_id=org_id, resource=resource, resource_id=resource_id)

    assert link.startswith(APP_BASE_URL)
    assert f"/orgs/{org_id}/{resource}" in link
    if resource_id:
        assert link.endswith(resource_id) or f"/{resource_id}" in link


@given(org_id=safe_text, resource=safe_text, extra_value=safe_text)
@settings(max_examples=50)
def test_deep_link_includes_query_params_when_given(org_id: str, resource: str, extra_value: str):
    link = build_deep_link(org_id=org_id, resource=resource, month=extra_value)
    assert "?" in link
    assert "month=" in link


# ---------------------------------------------------------------------------
# Property 3: whatever way the real SDK call fails, the job's run-agent step
# must ALWAYS log a result with a valid `source`, and a `fallback_reason`
# that is present iff the fallback path was used -- this is exactly the
# "why did it fall back with no visible error" bug from this session, now
# pinned down as an invariant instead of a single fixed example.
# ---------------------------------------------------------------------------

exception_types = st.sampled_from(
    [ConnectionError, TimeoutError, ValueError, RuntimeError, OSError]
)
exception_messages = st.text(min_size=1, max_size=80)


@given(exc_type=exception_types, exc_message=exception_messages)
@settings(max_examples=30)
@pytest.mark.asyncio
async def test_agent_run_failure_always_logged_with_real_cause(exc_type, exc_message):
    with patch(
        "ai_agents.api.financial_advisor_agent._SdkRunner.run",
        new=AsyncMock(side_effect=exc_type(exc_message)),
    ), patch("ai_agents.api.financial_advisor_agent._SdkAgent"), \
       patch("jobs.financial_agent_job.agent_jobs_repository.add_log") as mock_add_log, \
       patch("jobs.financial_agent_job.agent_jobs_repository.update_job_status"), \
       patch("jobs.financial_agent_job.get_supabase"):
        summary = {"total_sales": 100.0, "total_expenses": 50.0, "net_profit": 50.0}

        result = await _step_run_agent("job-1", "org-1", summary)

        # The step itself must never raise -- a broken AI call must degrade
        # to rule-based advice, not fail the whole job.
        assert result["source"] == "rule_based_fallback"
        assert result["advice"]

        # And the log written must actually name what went wrong.
        assert mock_add_log.called
        _, log_kwargs = mock_add_log.call_args
        insights = log_kwargs.get("insights_generated", {})
        fallback_reason = insights.get("fallback_reason")
        assert fallback_reason is not None, "a fallback must always log WHY it fell back"
        assert exc_type.__name__ in fallback_reason
        assert exc_message in fallback_reason


@pytest.mark.asyncio
async def test_agent_run_success_never_logs_a_fallback_reason():
    """The complementary case: when the real SDK genuinely succeeds, the
    log must NOT carry a fallback_reason, and source must say so honestly.
    """
    from types import SimpleNamespace

    with patch(
        "ai_agents.api.financial_advisor_agent._SdkRunner.run",
        new=AsyncMock(return_value=SimpleNamespace(final_output="Real AI advice.")),
    ), patch("ai_agents.api.financial_advisor_agent._SdkAgent"), \
       patch("jobs.financial_agent_job.agent_jobs_repository.add_log") as mock_add_log, \
       patch("jobs.financial_agent_job.agent_jobs_repository.update_job_status"), \
       patch("jobs.financial_agent_job.get_supabase"):
        summary = {"total_sales": 100.0, "total_expenses": 50.0, "net_profit": 50.0}

        result = await _step_run_agent("job-1", "org-1", summary)

        assert result["source"] == "openai_agent"
        assert result["advice"] == "Real AI advice."

        _, log_kwargs = mock_add_log.call_args
        insights = log_kwargs.get("insights_generated", {})
        assert "fallback_reason" not in insights
