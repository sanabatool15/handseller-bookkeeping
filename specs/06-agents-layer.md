# Agents Layer (`agents/`)

## What we did

Split the AI-facing code into four purpose-specific subfolders, exactly as
the spec for this step demanded:

- **`agents/prompts/*.md`** — every system/agent prompt as a Markdown file
  (`financial_advisor_system.md`, `financial_audit.md`), loaded at runtime
  by `agents/prompt_loader.py`. **No prompt text is ever a Python string
  literal in this codebase.**
- **`agents/api/financial_advisor_agent.py`** — orchestration against the
  OpenAI Agents SDK: builds an `Agent` with instructions loaded from
  `agents/prompts/financial_advisor_system.md`, runs it via `Runner.run(...)`
  against a JSON-serialized monthly summary, and returns the agent's final
  text output.
- **`agents/rules/fallback_engine.py`** — a fully deterministic, offline
  rule engine (`rule_based_financial_advice`) that produces useful advice
  from the same monthly-summary input **without any network call or LLM**.
- **`agents/tools/`** — small standalone utilities (`web_search.py`,
  `deep_link.py`) available to agent code, kept separate from orchestration
  logic so they can be tested/reused independently.

## Why we did it: prompts as files, not strings

Keeping prompts in `.md` files rather than Python strings means:

1. **Prompts can be edited, reviewed, and diffed like content, not code.**
   A non-engineer (or a future you, months later) can tune the financial
   advisor's tone or add a constraint without touching `.py` files or
   understanding string formatting/escaping inside Python source.
2. **Prompts are versioned independently of orchestration logic.** A change
   to how the agent is *prompted* doesn't require a code review of how it's
   *invoked* — these are genuinely different concerns and earlier ladder
   steps (before this constraint existed) mixed them together, making a
   simple wording tweak look like a code change in diffs.
3. **The same prompt is reusable across surfaces.** `financial_audit.md` is
   loaded both if you build a CLI/script around it later and by
   `mcp/server.py`'s `financial_audit` MCP prompt primitive — one file, one
   source of truth, instead of the prompt text duplicated in two Python
   modules.

## Why we did it: a deterministic rule-based fallback

The requirement to have `agents/rules/` as an **offline fallback engine**
(not just error handling) exists because a bookkeeping tool's users depend
on getting *some* actionable answer when they ask "how's my business
doing this month" — and an AI agent call is one of the least reliable
parts of the whole system (network dependency, API key configuration,
rate limits, cost). `jobs/financial_agent_job.py`'s `_step_run_agent`
catches *any* exception from `run_financial_advisor` and calls
`rule_based_financial_advice` instead — this means a misconfigured
`OPENAI_API_KEY`, a network outage, or (see below) the package-shadowing
issue never results in "sorry, no advice today," only in a simpler,
non-AI-generated version of the same advice. This is exercised directly in
`tests/unit/test_fallback_engine.py`.

## The `agents` package-name collision (read before changing imports here)

This is a real, previously reproduced problem, documented in
`agents/api/financial_advisor_agent.py`'s module docstring and in
`README.md`, not a theoretical concern:

**The `openai-agents` PyPI package installs as a top-level module also
named `agents`.** This repository's own `agents/` directory is *also* a
top-level package named `agents` (required by the spec's directory layout,
and by Python import resolution rules, once this repo's root is on
`sys.path` — which it always is when running `uvicorn app.main:app` from
the repo root). Python resolves `import agents` to whichever `agents`
package it finds first on `sys.path`, and — critically — **when the import
happens from *inside* this repo's own `agents/api/financial_advisor_agent.py`,
Python has already registered this local package as the module named
`agents` in `sys.modules` before that submodule's code even runs** (that's
how Python imports work: the parent package is imported before its
submodules). So `import agents` from inside `agents/api/...` always
resolves to *itself*, never to the real SDK, as long as the code lives
inside this repo's own `agents/` package.

**What we did about it:** `financial_advisor_agent.py` doesn't try to
"fix" the import — it detects the situation defensively:

```python
try:
    import agents as _oai_agents_module
    if hasattr(_oai_agents_module, "Agent") and hasattr(_oai_agents_module, "Runner"):
        _sdk_agent = _oai_agents_module.Agent
        _sdk_runner = _oai_agents_module.Runner
        _sdk_available = True
except ImportError:
    _sdk_available = False
```

If the imported `agents` module doesn't have `Agent`/`Runner` (i.e. it
resolved to this local package, not the SDK), `_sdk_available` stays
`False`, and `run_financial_advisor` raises `AgentUnavailableError` —
which the Inngest job step catches and treats exactly like any other agent
failure, routing to the rule-based fallback. **We chose to treat this as
"SDK unavailable" rather than attempting a `sys.path` hack or a runtime
import-order trick**, because those workarounds are fragile (they'd depend
on import order that could change with any refactor) and would hide a real
architectural constraint behind "clever" code that the next person has to
reverse-engineer.

**If you actually need the live OpenAI Agents SDK to run** (not just fall
back), the real fix is architectural, not a patch: run the agent-calling
code in a process/service where this repo's `agents/` package isn't what
`import agents` resolves to — e.g. as a separate microservice, in a
separate virtualenv/deployment unit, or by renaming one of the two
packages (this repo's `agents/` to something else, which would require
updating every import and the directory-structure requirement from the
original spec). Do not attempt to solve this with `sys.path` manipulation
inside the request/job path — treat it as a real decision to make
deliberately, and update this doc and `README.md` if you do.

## Where this is tested

- `tests/unit/test_financial_advisor_agent.py` — confirms the module
  correctly detects SDK-unavailable and raises `AgentUnavailableError`
  rather than crashing.
- `tests/unit/test_fallback_engine.py` — confirms the rule-based path
  produces sensible advice from a given monthly summary.
- `tests/unit/test_prompt_loader.py` — confirms prompts load from the
  `.md` files (and fail loudly, not silently with an empty string, if a
  prompt file is missing/renamed).
- `tests/unit/test_tools.py` — covers `agents/tools/`.
