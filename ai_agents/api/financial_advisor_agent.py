"""OpenAI Agents SDK orchestration for the financial advisor.

FIXED (previously documented limitation): this package used to be named
`agents/`, which collided with the top-level `agents` module installed by
the `openai-agents` PyPI package — `import agents` from inside that
package always resolved to itself, so the real SDK was structurally
unreachable no matter what was configured. This package is now named
`ai_agents/` specifically to free up the `agents` import for the real SDK.
`import agents` here now genuinely resolves to `openai-agents`.

The SDK can still legitimately be unavailable at runtime for ordinary
reasons — it isn't installed, there's no network, or `OPENAI_API_KEY`
isn't configured — and those are handled the same way as before:
`run_financial_advisor` raises `AgentUnavailableError`, which
`jobs/financial_agent_job.py` catches and falls back to
`ai_agents/rules/fallback_engine.py`. So a job always produces useful
advice, whether or not a live OpenAI account is configured in this
environment.
"""
from __future__ import annotations

import json
from typing import Any

from ai_agents.prompt_loader import load_prompt

try:
    from agents import Agent as _SdkAgent
    from agents import Runner as _SdkRunner

    _sdk_available = True
except ImportError:
    _sdk_available = False


class AgentUnavailableError(Exception):
    """Raised when the OpenAI Agents SDK cannot be used (not installed, no
    network, no API key, or the underlying API call fails for any other
    reason). Callers should catch this and use the rule-based fallback
    engine instead."""


async def run_financial_advisor(monthly_summary: dict[str, Any]) -> str:
    """Runs the financial-advisor agent against a monthly sales/expense summary.

    Raises AgentUnavailableError if the SDK isn't usable in this process
    (not installed) or the run itself fails (network, auth, no output), so
    the caller (the Inngest job step) can fall back to the deterministic
    rule engine and never leave the user without advice.
    """
    if not _sdk_available:
        raise AgentUnavailableError(
            "openai-agents is not installed in this environment. "
            "Install it (see pyproject.toml) to enable live AI-generated advice."
        )

    system_prompt = load_prompt("financial_advisor_system")

    agent = _SdkAgent(
        name="FinancialAdvisor",
        instructions=system_prompt,
    )
    user_message = (
        "Here is this month's financial summary as JSON:\n"
        f"{json.dumps(monthly_summary, default=str)}\n"
        "Provide your analysis and one concrete next action."
    )

    try:
        result = await _SdkRunner.run(agent, user_message)
    except Exception as exc:  # noqa: BLE001 - any SDK/network/auth failure
        raise AgentUnavailableError(f"Agent run failed: {exc}") from exc

    output = getattr(result, "final_output", None)
    if output is None:
        raise AgentUnavailableError("Agent run produced no output.")
    return str(output)
