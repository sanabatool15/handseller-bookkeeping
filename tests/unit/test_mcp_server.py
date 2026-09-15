"""Loads mcp/server.py directly (never via `import mcp...`, see that file's
docstring for why) and checks all 5 MCP primitives are registered."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MCP_SERVER_PATH = Path(__file__).resolve().parents[2] / "mcp" / "server.py"


@pytest.fixture
def mcp_module(_wire_fakes):
    spec = importlib.util.spec_from_file_location("handseller_mcp_server_under_test", MCP_SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_tools_registered(mcp_module):
    tools = await mcp_module.mcp.list_tools()
    names = {t.name for t in tools}
    assert {"log_sale", "log_expense", "trigger_financial_agent_job"}.issubset(names)


@pytest.mark.asyncio
async def test_resource_template_registered(mcp_module):
    templates = await mcp_module.mcp.list_resource_templates()
    uris = {t.uri_template for t in templates}
    assert "ledger://{org_id}/monthly.csv" in uris


@pytest.mark.asyncio
async def test_prompt_registered(mcp_module):
    prompts = await mcp_module.mcp.list_prompts()
    names = {p.name for p in prompts}
    assert "financial_audit" in names


@pytest.mark.asyncio
async def test_log_sale_tool_creates_a_sale(mcp_module):
    # Call the underlying handler directly (bypassing the MCP session/Context
    # machinery, which requires a live client connection) to unit-test the
    # tool's business logic without spinning up a full stdio session.
    sale = await mcp_module.log_sale(org_id="org-mcp", user_id="user-mcp", amount=25.0, category="retail")
    assert sale["amount"] == 25.0
    assert sale["org_id"] == "org-mcp"
