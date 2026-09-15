"""Thin web-search utility tool the agent can call for external context
(e.g. current interest rates, tax deadlines). Kept isolated behind httpx so
it's easy to mock in tests, and never imported directly by the fallback
rule engine (which must work fully offline).
"""
from __future__ import annotations

import httpx


async def web_search(query: str, *, max_results: int = 3) -> list[dict[str, str]]:
    """Best-effort web search. Returns an empty list on any failure rather
    than raising, so a flaky network never breaks the agent workflow.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return []

    # Best-effort: real result parsing is out of scope for this backend;
    # callers should treat this as a placeholder integration point.
    return [{"query": query, "note": "web_search executed", "result_count": str(max_results)}]
