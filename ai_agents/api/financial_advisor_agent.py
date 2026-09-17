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
import logging
from typing import Any
from dotenv import load_dotenv
import os
from ai_agents.prompt_loader import load_prompt


load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_API_BASE_URL")
MODEL     = os.getenv("OPENAI_MODEL")
try:
    from agents import Agent as _SdkAgent
    from agents import Runner as _SdkRunner
    from agents import set_default_openai_client as _set_default_openai_client
    from openai import AsyncOpenAI as _AsyncOpenAI

    # Agent(...) itself has no api_key/base_url kwargs (verified against the
    # installed openai-agents package: Agent.__init__ only accepts a `model`
    # string/Model, not api_key/base_url). A custom endpoint (e.g. OpenRouter)
    # must be configured via a client set as the SDK's default instead.
    if API_KEY and BASE_URL:
        _set_default_openai_client(
            _AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL),
            use_for_tracing=False,  # tracing uploads go to OpenAI's own API, not OpenRouter
        )

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
        model=MODEL,
    )
    user_message = (
        "Here is this month's financial summary as JSON:\n"
        f"{json.dumps(monthly_summary, default=str)}\n"
        "Provide your analysis and one concrete next action."
    )

    try:
        result = await _SdkRunner.run(agent, user_message)
    except Exception as exc:  # noqa: BLE001 - any SDK/network/auth failure
        logger.exception("Financial advisor agent run failed; falling back to rule-based advice")
        raise AgentUnavailableError(f"Agent run failed: {type(exc).__name__}: {exc}") from exc

    output = getattr(result, "final_output", None)
    if output is None:
        raise AgentUnavailableError("Agent run produced no output.")
    return str(output)
