"""Run the financial-advisor agent directly, with no Docker/Inngest/Supabase.

This exercises exactly the same call jobs/financial_agent_job.py makes
(ai_agents.api.financial_advisor_agent.run_financial_advisor), against a
made-up summary, so you can see whether the real OpenAI Agents SDK / your
OpenRouter config actually works -- in seconds, without a full
`docker compose up --build` cycle.

Usage:
    python tests/run_agent_locally.py

Requires only OPENAI_API_KEY / OPENAI_API_BASE_URL / OPENAI_MODEL to be
set in .env (same file docker compose uses). Nothing else needs to be
running.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    print("=" * 70)
    print("Financial advisor agent -- direct local run (no Docker)")
    print("=" * 70)

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    print(f"OPENAI_API_KEY       = {'set (' + api_key[:8] + '...)' if api_key else 'NOT SET'}")
    print(f"OPENAI_API_BASE_URL  = {base_url or 'NOT SET'}")
    print(f"OPENAI_MODEL         = {model or 'NOT SET'}")
    print("-" * 70)

    if not api_key or not base_url:
        print("Missing OPENAI_API_KEY or OPENAI_API_BASE_URL in .env -- the agent")
        print("will raise AgentUnavailableError immediately. Fix .env and re-run.")
        print("=" * 70)
        return

    # Imported after load_dotenv() and after the checks above so the
    # module-level client setup in financial_advisor_agent.py sees the
    # same env vars a real docker compose run would.
    from ai_agents.api.financial_advisor_agent import AgentUnavailableError, run_financial_advisor
    from app.clients import get_supabase

    db = get_supabase()
    sample_summary = {
        "total_sales": 4250.00,
        "total_expenses": 1830.50,
        "net_profit": 2419.50,
        "top_selling_items": ["candles", "soap bars", "lotion"],
    }
    print("Calling run_financial_advisor() with a sample summary:")
    print(f"  {sample_summary}")
    print("-" * 70)

    started = time.monotonic()
    try:
        advice = await run_financial_advisor(db, sample_summary)
    except AgentUnavailableError as exc:
        elapsed = time.monotonic() - started
        print(f"RESULT: AgentUnavailableError after {elapsed:.1f}s")
        print(f"  {exc}")
        print()
        print("This is the exact error the Inngest job step would catch and log")
        print("before falling back to rule_based_financial_advice. If this message")
        print("names a real cause (DNS, 401, model not found, etc.), fix that and")
        print("re-run this script -- no need to touch Docker until this passes.")
    else:
        elapsed = time.monotonic() - started
        print(f"RESULT: success in {elapsed:.1f}s (source=openai_agent)")
        print("-" * 70)
        print(advice)

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
