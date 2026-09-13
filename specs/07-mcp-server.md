# Model Context Protocol Server (`mcp/server.py`)

## What we did

Built a `FastMCP`-based server, run over **stdio transport**, at
`mcp/server.py`, implementing all 5 MCP primitives against this app's real
`services/`/`repository/` layer (not a separate reimplementation):

1. **Tools** — `log_sale`, `log_expense`, `trigger_financial_agent_job`
   (the three required by spec), plus two bonus tools that exist
   specifically to demonstrate primitives 4 and 5:
   `summarize_ledger_via_client_llm` (sampling) and `stream_job_logs`
   (logging).
2. **Resources** — `ledger://{org_id}/monthly.csv`, a resource *template*
   (the `{org_id}` is a variable segment) that reads live sales/expenses
   from Postgres via `services.financial_report_service.monthly_ledger_csv`
   and returns a raw CSV string — an MCP client can "open" this like a
   file/URI, not just call it like an API.
3. **Prompts** — `financial_audit(org_id)`, which loads
   `agents/prompts/financial_audit.md` via `agents/prompt_loader.py` and
   pre-fills it with the org's current-month ledger CSV, so a connected
   client (e.g. Claude Desktop) can offer "run a financial audit for this
   org" as a ready-made, context-filled prompt.
4. **Sampling** — `summarize_ledger_via_client_llm` issues an MCP
   `sampling/createMessage` request via `ctx.session.create_message(...)`.
   This tool **never calls OpenAI or any server-side LLM directly** — it
   asks the *connected MCP client* to run the completion, so the client
   (not this server) pays for and controls the inference.
5. **Logging** — every tool calls `await ctx.log(...)` (or `ctx.error(...)`
   on failure), streaming structured log notifications to the connected
   client's log stream in real time, in addition to returning normal tool
   results. `stream_job_logs` additionally re-emits a job's `agent_logs`
   rows as a sequence of log notifications on demand, so a client can
   "replay" a background job's history through the same log stream.

Every MCP tool calls the exact same `services.*` functions the HTTP routers
call — `log_sale`/`log_expense` go through `services.sales_service` /
`services.expenses_service`, and `trigger_financial_agent_job` goes through
`services.agent_job_service.trigger_financial_advice_job` (the same
function `POST /agent-jobs/financial-advice` uses). There is no parallel
MCP-specific business logic anywhere.

## Why we did it

The point of exposing an MCP server at all is to let external LLM clients
(Claude Desktop, other MCP-compatible tools) act as a front-end onto this
bookkeeping system — a handseller (or their accountant) using an AI chat
client should be able to log a sale, pull this month's ledger, or ask for
a financial audit, without that client needing a bespoke integration
against this app's REST API. MCP standardizes that integration surface.

**Why route through the same `services/` layer instead of writing
MCP-specific logic:** this guarantees an MCP-invoked action has *identical*
validation and multi-tenant scoping to the same action performed via the
REST API — there's no separate code path that could accidentally be less
strict. This is a direct consequence of the layering decision in
`01-architecture-layering.md`: because routers are thin adapters onto
services, MCP tools can be thin adapters onto the exact same services too.

**Why sampling matters specifically for this app:** a bookkeeping backend
that also called an LLM server-side for every "summarize my ledger"
request would mean *this server* pays OpenAI costs on behalf of every
connected client, with no natural way to attribute or limit that spend per
user. Client-side sampling inverts that — the MCP client (which already
has its own LLM relationship, e.g. the user's own Claude subscription)
performs the inference, and this server only supplies the data and the
question. This is the correct cost/ownership model for a tool meant to be
used by many different external clients.

## The `mcp` package-name collision (read before touching imports here)

This is a real, previously reproduced problem, not theoretical:

**The `mcp` Python SDK (a dependency of `fastmcp`) installs as a top-level
package also named `mcp`.** This repository is required by the spec to put
its MCP server at the path `mcp/server.py` — meaning this repo also has a
directory named `mcp/`. If that directory were an importable Python
package (i.e. had an `__init__.py`) and got imported as `mcp` *before* the
real SDK's `mcp` package, it would shadow the SDK entirely. **We verified
this concretely**: with an `__init__.py` present and this directory
resolvable as `mcp`, `import fastmcp` fails with
`ModuleNotFoundError: No module named 'mcp.server'`, because `fastmcp`
internally does `from mcp.server import ...` and gets this repo's
`mcp/server.py` instead of the SDK's.

**What we did about it:**

- `mcp/` in this repo **deliberately has no `__init__.py`** — it is not an
  importable Python package, just a directory that happens to contain
  `server.py`.
- `mcp/server.py` is **never imported** anywhere in this codebase (or its
  tests) via `import mcp.server` or `from mcp.server import ...`. It's
  always either run directly as a script (`python mcp/server.py`, or
  `fastmcp run mcp/server.py`), or — in `tests/unit/test_mcp_server.py` —
  loaded via `importlib.util.spec_from_file_location(...)` under a distinct
  module name, which sidesteps the package-name resolution entirely.
- `mcp/server.py` manually inserts the repo root onto `sys.path` at the top
  of the file (`_REPO_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, ...)`)
  so that its own imports of `app`, `repository`, `services`, `agents`
  work correctly when it's run directly as a script from anywhere.

**Do not add an `__init__.py` to `mcp/`, and do not add
`from mcp.server import ...` anywhere in this codebase** without
re-verifying this collision doesn't reappear — `tests/unit/test_mcp_server.py`
exists specifically as a regression test proving the server still loads
and registers all 5 primitives correctly under this repo's actual layout,
not a simplified/isolated version of it.

## Running it

```bash
python mcp/server.py
# or:
fastmcp run mcp/server.py
```

Connect any MCP-compatible client (Claude Desktop, the `mcp` CLI
inspector) over stdio by pointing its config at that command — see
`README.md`'s example Claude Desktop config entry.

## Documented SDK-version assumption

Verified against **`fastmcp==4.0.3`** by installing it and inspecting the
real decorator/context API (`@mcp.tool`, `@mcp.resource(...)`, `@mcp.prompt`,
`ctx.log`/`ctx.error`, `ctx.session.create_message`) rather than assuming
from documentation alone.

## Where this is tested

`tests/unit/test_mcp_server.py` loads the server module via
`importlib.util` and asserts all 5 primitives are registered (tools,
resource template, prompt) under this repo's real layout — this is what
proves the package-collision workaround above actually holds, not just
that it holds in a simplified reproduction. Sampling and logging are
inherently interactive, client-driven MCP features (they require a real
connected client that supports the corresponding protocol capability), so
they are verified by confirming correct *registration* and code review
rather than an automated end-to-end test against a live external client —
see `10-known-limitations.md`.
