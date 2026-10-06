"""OpenAI Agents SDK orchestration for the bookkeeping assistant.

Package renamed `agents/` -> `ai_agents/` so `import agents` resolves to the
real `openai-agents` SDK instead of shadowing itself.

Three agents: `planner_agent` (no tools, just hands off via `handoff()` so
conversation history carries over) routes to `investigate_agent` (read-only
summary/breakdown tools + `web_search`) or `record_agent` (record-creation
tools + `deep_link`). Both specialists return a structured
`BookkeepingResult`; the whole chain runs as one `Runner.run_streamed()`
call with an `error_handlers={"max_turns": ...}` fallback to the rule engine.

`run_bookkeeping_agent` raises `AgentUnavailableError` for any ordinary
failure (not installed, no network, no API key, live-call error), which
`jobs/financial_agent_job.py` catches and falls back to
`ai_agents/rules/fallback_engine.py`.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel
from supabase import Client

from ai_agents.prompt_loader import load_prompt
from ai_agents.tools.bookkeeping_tools import build_investigate_tools, build_record_tools

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_API_BASE_URL")
MODEL = os.getenv("OPENAI_MODEL")

DEFAULT_MAX_TURNS = 10


class BookkeepingResult(BaseModel):
    """Structured final output both specialists produce. `mode` records
    which specialist actually answered, independent of prose parsing."""

    mode: Literal["investigation", "record_entry"]
    summary: str
    root_cause: str | None = None
    recommendation: str | None = None
    used_web_search: bool = False
    record_reference: str | None = None


try:
    from agents import Agent as _SdkAgent
    from agents import Runner as _SdkRunner
    from agents import handoff as _sdk_handoff
    from agents import set_default_openai_client as _set_default_openai_client
    from agents.models.openai_chatcompletions import (
        OpenAIChatCompletionsModel as _OpenAIChatCompletionsModel,
    )
    from agents.run_error_handlers import RunErrorHandlerResult as _RunErrorHandlerResult
    from openai import AsyncOpenAI as _AsyncOpenAI

    # Agent(...) has no api_key/base_url kwargs, so a custom endpoint (e.g.
    # OpenRouter) is wired via an explicit OpenAIChatCompletionsModel +
    # AsyncOpenAI client instead — this also sidesteps MultiProvider's "/"
    # prefix parsing, which would otherwise mis-route OpenRouter-style model
    # IDs like "inclusionai/<model>". Not re-verified against a real
    # OpenRouter model + 3-agent handoffs + output_type combination.
    _openai_client = _AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY and BASE_URL else None
    if _openai_client is not None:
        _set_default_openai_client(_openai_client, use_for_tracing=False)

    _sdk_available = True
except ImportError:
    _sdk_available = False


class AgentUnavailableError(Exception):
    """Raised when the OpenAI Agents SDK cannot be used (not installed, no
    network, no API key, or the underlying API call fails for any other
    reason). Callers should catch this and use the rule-based fallback
    engine instead."""


def _model_for(name: str):
    return (
        _OpenAIChatCompletionsModel(model=MODEL, openai_client=_openai_client)
        if _openai_client is not None
        else MODEL
    )


def build_agents(db: Client, *, org_id: str, user_id: str):
    """Builds the planner + two specialists, fresh per run, with tools
    closed over this run's org_id/user_id so the LLM can never supply (or
    be tricked into supplying) a different org's identity."""
    investigate_agent = _SdkAgent(
        name="Investigate agent",
        instructions=load_prompt("investigate_agent"),
        model=_model_for("investigate"),
        tools=build_investigate_tools(db, org_id=org_id),
        output_type=BookkeepingResult,
    )

    record_agent = _SdkAgent(
        name="Record agent",
        instructions=load_prompt("record_agent"),
        model=_model_for("record"),
        tools=build_record_tools(db, org_id=org_id, user_id=user_id),
        output_type=BookkeepingResult,
    )

    planner_agent = _SdkAgent(
        name="Planner agent",
        instructions=load_prompt("planner_agent"),
        model=_model_for("planner"),
        tools=[],  # deliberately none — the planner only routes, never answers
        handoffs=[_sdk_handoff(investigate_agent), _sdk_handoff(record_agent)],
    )

    return planner_agent, investigate_agent, record_agent


async def run_bookkeeping_agent(
    db: Client,
    *,
    org_id: str,
    user_id: str,
    user_message: str,
    fallback_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs the planner -> handoff -> specialist chain for one user message.

    Returns a dict with the specialist's routing decision (`agent_name`)
    and its structured `BookkeepingResult` (as a dict), or raises
    AgentUnavailableError so the caller can fall back to the deterministic
    rule engine.
    """
    if not _sdk_available:
        raise AgentUnavailableError(
            "openai-agents is not installed in this environment. "
            "Install it (see pyproject.toml) to enable live AI-generated advice."
        )

    from ai_agents.rules.fallback_engine import rule_based_financial_advice

    def _on_max_turns(_error_input):
        advice = rule_based_financial_advice(fallback_summary or {})
        return _RunErrorHandlerResult(
            final_output=BookkeepingResult(mode="investigation", summary=advice),
            include_in_history=False,
        )

    planner_agent, _investigate_agent, _record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    try:
        result = _SdkRunner.run_streamed(
            planner_agent,
            user_message,
            max_turns=DEFAULT_MAX_TURNS,
            error_handlers={"max_turns": _on_max_turns},
        )

        async for event in result.stream_events():
            if getattr(event, "type", None) == "agent_updated_stream_event":
                logger.info("Handed off to: %s", getattr(event.new_agent, "name", "?"))
            elif getattr(event, "type", None) == "run_item_stream_event":
                logger.debug("Run item event: %s", getattr(event, "name", "?"))
    except Exception as exc:  # noqa: BLE001 - any SDK/network/auth failure
        logger.exception("Bookkeeping agent run failed; falling back to rule-based advice")
        raise AgentUnavailableError(f"Agent run failed: {type(exc).__name__}: {exc}") from exc

    output = getattr(result, "final_output", None)
    if output is None:
        raise AgentUnavailableError("Agent run produced no output.")

    last_agent = getattr(result, "last_agent", None)
    output_dict = output.model_dump() if isinstance(output, BaseModel) else {"summary": str(output)}
    return {
        "agent_name": getattr(last_agent, "name", None),
        "result": output_dict,
    }


async def run_financial_advisor(db: Client, monthly_summary: dict[str, Any]) -> str:
    """Backward-compatible entry point used by the proactive monthly-advice
    job: synthesizes an investigation request from the monthly summary
    (routing it to `investigate_agent` via the planner, same as any other
    "how's my business doing" question) and returns the resulting advice as
    a plain string, same shape the caller expects.

    `db` must be supplied by the caller (the job already holds one from the
    job context/token-derived org_id) — this module never obtains its own
    Supabase client, per the routers -> services -> repository layering.

    Raises AgentUnavailableError on any failure so the caller falls back to
    `ai_agents/rules/fallback_engine.py`.
    """
    import json

    org_id = str(monthly_summary.get("org_id") or "unknown-org")
    user_message = (
        "Here is this month's financial summary as JSON:\n"
        f"{json.dumps(monthly_summary, default=str)}\n"
        "How is the business doing, and what's the single most important thing to act on?"
    )

    outcome = await run_bookkeeping_agent(
        db,
        org_id=org_id,
        user_id="system",
        user_message=user_message,
        fallback_summary=monthly_summary,
    )
    result = outcome["result"]
    parts = [p for p in (result.get("summary"), result.get("recommendation")) if p]
    text = " ".join(parts) if parts else str(result)
    if not text.strip():
        raise AgentUnavailableError("Agent run produced no usable output.")
    return text
