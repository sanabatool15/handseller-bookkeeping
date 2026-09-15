"""OpenAI Agents SDK orchestration for the financial advisor.

IMPORTANT NAMESPACE NOTE (documented assumption/limitation — see README):
The `openai-agents` PyPI package installs as a top-level module named
`agents`, which collides with this project's own `agents/` package (required
by the spec's directory layout). When this repo's root is on `sys.path`
(the normal case when running `uvicorn app.main:app` from the repo root),
`import agents` resolves to *this* local package rather than the SDK,
shadowing it. We defensively detect that case below and treat it exactly
like "SDK unavailable" — falling through to the rule-based engine in
`agents/rules/fallback_engine.py` — rather than crashing. In a deployment
where this collision is unacceptable, rename either this package or install
the SDK under an alias (e.g. `pip install openai-agents` in a separate
virtualenv/service boundary from this codebase).
"""
from __future__ import annotations

import json
from typing import Any

from agents.prompt_loader import load_prompt

_sdk_agent = None
_sdk_runner = None
_sdk_available = False

try:
    import agents as _oai_agents_module  # may resolve to the SDK OR shadow to this local package

    if hasattr(_oai_agents_module, "Agent") and hasattr(_oai_agents_module, "Runner"):
        _sdk_agent = _oai_agents_module.Agent
        _sdk_runner = _oai_agents_module.Runner
        _sdk_available = True
except ImportError:
    _sdk_available = False


class AgentUnavailableError(Exception):
    """Raised when the OpenAI Agents SDK cannot be used (import shadowed, no
    network, no API key). Callers should catch this and use the rule-based
    fallback engine instead."""


async def run_financial_advisor(monthly_summary: dict[str, Any]) -> str:
    """Runs the financial-advisor agent against a monthly sales/expense summary.

    Raises AgentUnavailableError if the SDK isn't usable in this process, so
    the caller (the Inngest job step) can fall back to the deterministic
    rule engine and never leave the user without advice.
    """
    if not _sdk_available:
        raise AgentUnavailableError("OpenAI Agents SDK is not available in this process (see module docstring).")

    system_prompt = load_prompt("financial_advisor_system")

    agent = _sdk_agent(
        name="FinancialAdvisor",
        instructions=system_prompt,
    )
    user_message = (
        "Here is this month's financial summary as JSON:\n"
        f"{json.dumps(monthly_summary, default=str)}\n"
        "Provide your analysis and one concrete next action."
    )

    result = await _sdk_runner.run(agent, user_message)
    output = getattr(result, "final_output", None)
    if output is None:
        raise AgentUnavailableError("Agent run produced no output.")
    return str(output)
