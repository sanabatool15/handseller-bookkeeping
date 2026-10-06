"""Imports `mcp_gateway.server` normally and checks all 5 MCP primitives are
registered.

FIXED (previously documented limitation): this used to require loading
`mcp/server.py` via `importlib.util.spec_from_file_location(...)` to avoid
a package-name collision with the real `mcp` SDK (see git history / the
old spec doc). Now that the package is named `mcp_gateway/`, it's a normal
importable package with no collision, so a normal `from mcp_gateway.server
import ...` works and this test no longer needs the importlib workaround.
"""
from __future__ import annotations

import pytest

from mcp_gateway import server as mcp_module


@pytest.mark.asyncio
async def test_tools_registered():
    tools = await mcp_module.mcp.list_tools()
    names = {t.name for t in tools}
    assert {"log_sale", "log_expense", "trigger_financial_agent_job"}.issubset(names)


@pytest.mark.asyncio
async def test_resource_template_registered():
    templates = await mcp_module.mcp.list_resource_templates()
    uris = {t.uri_template for t in templates}
    assert "ledger://{org_id}/monthly.csv" in uris


@pytest.mark.asyncio
async def test_prompt_registered():
    prompts = await mcp_module.mcp.list_prompts()
    names = {p.name for p in prompts}
    assert "financial_audit" in names


@pytest.mark.asyncio
async def test_log_sale_tool_creates_a_sale(_wire_fakes):
    # Call the underlying handler directly (bypassing the MCP session/Context
    # machinery, which requires a live client connection) to unit-test the
    # tool's business logic without spinning up a full stdio session.
    sale = await mcp_module.log_sale(org_id="org-mcp", user_id="user-mcp", amount=25.0, category="retail")
    assert sale["amount"] == 25.0
    assert sale["org_id"] == "org-mcp"
