# Package-name collisions with third-party SDKs — fixed by renaming

These were real, previously-reproduced bugs, not theoretical — and they are
now **fixed**, not worked around. Both fixes were the same shape: this
repo's own package had the same name as a required third-party SDK, so
Python's own package always shadowed the SDK. Renaming our package (not
the SDK) fixed it permanently.

- **`mcp` PyPI package (a dependency of `fastmcp`) vs. this repo's own
  directory.** Used to be `mcp/`, which — if given an `__init__.py` and
  imported as `mcp` before the real SDK — broke `import fastmcp` entirely
  (`ModuleNotFoundError: No module named 'mcp.server'`, verified). **Fixed:
  the directory is now `mcp_gateway/`.** It has a normal `__init__.py` and
  is imported normally (`from mcp_gateway.server import mcp`, `python
  mcp_gateway/server.py`). `mcp_gateway/server.py`'s own
  `from mcp.types import ...` and `from fastmcp import ...` now correctly
  resolve to the real SDK. **Do not rename this directory back to `mcp/`
  or give any directory literally named `mcp/` an `__init__.py`** in this
  repo — that reintroduces the exact collision.

- **`agents` PyPI package (`openai-agents`) vs. this repo's own
  directory.** Used to be `agents/`, which meant `import agents` from
  *inside* that same package always resolved to itself (Python resolves a
  package's own name before importing its submodules) — the real SDK was
  **structurally unreachable**, permanently, regardless of installation or
  API key configuration. **Fixed: the directory is now `ai_agents/`.**
  `import agents` inside `ai_agents/api/financial_advisor_agent.py` now
  genuinely resolves to the real `openai-agents` SDK.
  `run_financial_advisor` still raises `AgentUnavailableError` (caught by
  the Inngest job step, which falls back to
  `ai_agents/rules/fallback_engine.py`) — but now only for *ordinary*
  reasons an external API can fail: not installed, no network, no
  `OPENAI_API_KEY`, or the live call itself erroring. **Do not rename this
  directory back to `agents/`** — that reintroduces the exact collision and
  makes the SDK unreachable again.

If you ever need to rename either package again (or add a new package that
might collide with a third-party import), verify with
`python -c "import agents; print(agents.__file__)"` /
`python -c "import mcp; print(mcp.__file__)"` that the import resolves to
the third-party package's site-packages path, not somewhere inside this
repo, before trusting anything downstream of that import.
