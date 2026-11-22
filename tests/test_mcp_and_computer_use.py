"""Tests for Phase 3: MCP Client Manager and macOS Computer Use tools."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from src.agent.registry import ToolRegistry, ToolRiskTier
from src.tools.mcp_client import MCPClientManager, infer_mcp_risk_tier
from src.tools.mac_computer_use import register_mac_computer_use_tools


def test_mcp_risk_tier_classification():
    assert infer_mcp_risk_tier("list_issues") == ToolRiskTier.SAFE
    assert infer_mcp_risk_tier("get_pull_request") == ToolRiskTier.SAFE
    assert infer_mcp_risk_tier("search_code") == ToolRiskTier.SAFE
    assert infer_mcp_risk_tier("create_issue") == ToolRiskTier.CONFIRM
    assert infer_mcp_risk_tier("delete_branch") == ToolRiskTier.DANGEROUS


@pytest.mark.anyio
async def test_mcp_client_connects_to_real_stdio_server_and_executes_tool(tmp_path: Path):
    # Spin up a minimal real MCP server script using the installed mcp SDK
    server_script = tmp_path / "echo_mcp_server.py"
    server_script.write_text(
        '''
from mcp.server.mcpserver import MCPServer
mcp = MCPServer("EchoTest")

@mcp.tool()
def get_greeting(name: str) -> str:
    """Return a clean greeting."""
    return f"Hello from MCP, {name}!"

@mcp.tool()
def create_note(title: str) -> str:
    """Mutating action to verify CONFIRM tier assignment."""
    return f"Created note: {title}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''.strip()
    )

    cfg_path = tmp_path / "mcp_servers.json"
    cfg_path.write_text(
        json.dumps(
            {
                "servers": {
                    "echo_srv": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server_script)],
                        "enabled": True,
                    },
                    "disabled_srv": {
                        "transport": "stdio",
                        "command": "false",
                        "args": [],
                        "enabled": False,
                    },
                }
            }
        )
    )

    registry = ToolRegistry()
    manager = MCPClientManager(cfg_path, registry)
    await manager.reload()

    try:
        statuses = {s["name"]: s for s in manager.list_servers_status()}
        assert statuses["echo_srv"]["connected"] is True
        assert statuses["echo_srv"]["tool_count"] == 2
        assert statuses["disabled_srv"]["enabled"] is False
        assert statuses["disabled_srv"]["connected"] is False

        assert registry.get_tier("mcp__echo_srv__get_greeting") == ToolRiskTier.SAFE
        assert registry.get_tier("mcp__echo_srv__create_note") == ToolRiskTier.CONFIRM

        res = await registry.execute("mcp__echo_srv__get_greeting", {"name": "Boss"})
        assert res.ok is True
        assert "Hello from MCP, Boss!" in res.output
    finally:
        await manager.close_all()


@pytest.mark.anyio
async def test_mac_computer_use_registers_tiers_and_runs_clipboard_and_ui_tree():
    reg = ToolRegistry()
    register_mac_computer_use_tools(reg)

    assert reg.get_tier("get_clipboard") == ToolRiskTier.SAFE
    assert reg.get_tier("get_ui_tree") == ToolRiskTier.SAFE
    assert reg.get_tier("send_mac_notification") == ToolRiskTier.SAFE
    assert reg.get_tier("set_clipboard") == ToolRiskTier.CONFIRM
    assert reg.get_tier("ui_action") == ToolRiskTier.CONFIRM

    with patch("src.tools.mac_computer_use._run_exec", new=AsyncMock(return_value=(0, "clipboard sample", ""))):
        clip = await reg.execute("get_clipboard", {})
        assert clip.ok is True
        assert "clipboard sample" in clip.output
