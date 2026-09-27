async def web_search(query: str, *, max_results: int = 3) -> list[dict[str, str]]:
    """Best-effort web search. Returns explicit status so the agent knows
    whether it succeeded or failed, preventing infinite loops.
    """
    try:
        # Added a User-Agent header; without this, DuckDuckGo usually returns a 403 Forbidden instantly.
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            resp.raise_for_status()
            
            # Real success, but parsing is out of scope per your backend rules.
            # Tell the LLM exactly what happened so it stops searching.
            return [{
                "status": "success",
                "query": query,
                "system_note": "Search request succeeded, but HTML parsing is unimplemented. DO NOT search again. Inform the user that you cannot browse the live web yet."
            }]
            
    except Exception as e:
        # Real error. Tell the LLM it failed so it stops searching.
        return [{
            "status": "error",
            "query": query,
            "system_note": f"Search failed due to network exception: {type(e).__name__}. DO NOT search again. Inform the user that live search is currently unavailable."
        }]