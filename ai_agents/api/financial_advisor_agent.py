"""OpenAI Agents SDK orchestration for the bookkeeping assistant.

FIXED (previously documented limitation): this package used to be named
`agents/`, which collided with the top-level `agents` module installed by
the `openai-agents` PyPI package — `import agents` from inside that
package always resolved to itself, so the real SDK was structurally
unreachable no matter what was configured. This package is now named
`ai_agents/` specifically to free up the `agents` import for the real SDK.
`import agents` here now genuinely resolves to `openai-agents`.

Architecture (v2 — planner + handoff, see the design plan this implements):
three agents instead of one.

- `planner_agent` holds no bookkeeping tools at all — its only job is
  reading the user's message and handing off to whichever specialist fits
  (`handoff()`, not `Agent.as_tool()`, so the full conversation history,
  including the planner's own stated reasoning, carries over automatically).
- `investigate_agent` holds the read-only summary/breakdown tools plus
  `web_search`, and answers "how's my business doing / why" questions.
- `record_agent` holds the record-creation tools plus `deep_link`, and
  answers "I spent/sold X" statements by recording them directly (no
  approval gate — see the design plan's Section 7).

Both specialists return a structured `BookkeepingResult`. The whole chain —
planner hop, handoff, specialist's own tool calls — runs as a single
`Runner.run_streamed()` call starting at `planner_agent`, under one
`max_turns` budget, with an `error_handlers={"max_turns": ...}` fallback to
the existing deterministic rule engine.

The SDK can still legitimately be unavailable at runtime for ordinary
reasons — it isn't installed, there's no network, or `OPENAI_API_KEY`
isn't configured — and those are handled the same way as before:
`run_bookkeeping_agent` raises `AgentUnavailableError`, which
`jobs/financial_agent_job.py` catches and falls back to
`ai_agents/rules/fallback_engine.py`. So a job always produces useful
advice, whether or not a live OpenAI account is configured in this
environment.
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

    # Agent(...) itself has no api_key/base_url kwargs (verified against the
    # installed openai-agents package: Agent.__init__ only accepts a `model`
    # string/Model, not api_key/base_url). A custom endpoint (e.g. OpenRouter)
    # must be configured via a client passed explicitly instead.
    #
    # Also: Runner.run() builds its own MultiProvider internally when Agent's
    # `model` is a bare string, and MultiProvider parses any "/" in the model
    # name as "<prefix>/<model>", erroring with UserError("Unknown prefix: ...")
    # for any prefix it doesn't recognize (verified against the installed
    # package's MultiProvider._resolve_prefixed_model — only "openai",
    # "litellm", "any-llm" are built in). OpenRouter model IDs are commonly
    # namespaced like "inclusionai/<model>", which isn't one of those, so a
    # bare string silently mis-routes and fails. Passing an explicit
    # OpenAIChatCompletionsModel(model=..., openai_client=...) instead makes
    # Agent.model a Model object, bypassing MultiProvider's prefix parsing
    # entirely and sending the model string to our own client as-is.
    #
    # OPEN QUESTION (plan Section 10, item 2): this OpenRouter wiring path
    # was carried over unchanged from the single-agent version and has not
    # been re-verified against a real OpenRouter model + 3-agent handoffs +
    # output_type combination — flagged for a human to confirm.
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


async def run_financial_advisor(monthly_summary: dict[str, Any]) -> str:
    """Backward-compatible entry point used by the proactive monthly-advice
    job: synthesizes an investigation request from the monthly summary
    (routing it to `investigate_agent` via the planner, same as any other
    "how's my business doing" question) and returns the resulting advice as
    a plain string, same shape the caller expects.

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

    db: Client | None = None
    try:
        from app.clients import get_supabase

        db = get_supabase()
    except Exception:  # noqa: BLE001 - db may be unavailable outside a real run; tools that need it will raise
        db = None

    outcome = await run_bookkeeping_agent(
        db,  # type: ignore[arg-type]
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
