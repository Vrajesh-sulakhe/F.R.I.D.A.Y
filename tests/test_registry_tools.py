"""Tests for ToolRegistry risk tiers, workspace tools, and secret boundaries."""
from pathlib import Path
import pytest

from src.agent.registry import ToolRegistry, ToolRiskTier, RegisteredTool, ToolExecutionResult
from src.tools.workspace import build_default_registry


@pytest.mark.anyio
async def test_registry_register_and_execute_async_and_sync():
    reg = ToolRegistry()

    def sync_add(a: int, b: int) -> ToolExecutionResult:
        return ToolExecutionResult(ok=True, output=str(a + b), data={"sum": a + b})

    async def async_echo(msg: str) -> ToolExecutionResult:
        return ToolExecutionResult(ok=True, output=msg.upper())

    reg.register(
        RegisteredTool(
            name="add",
            description="Add two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
            handler=sync_add,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    reg.register(
        RegisteredTool(
            name="echo",
            description="Echo uppercase",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            handler=async_echo,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )

    defs = reg.list_definitions()
    assert [d.name for d in defs] == ["add", "echo"]
    assert reg.get_tier("add") == ToolRiskTier.SAFE
    assert reg.get_tier("echo") == ToolRiskTier.CONFIRM

    res_sync = await reg.execute("add", '{"a": 3, "b": 4}')
    assert res_sync.ok is True
    assert res_sync.data["sum"] == 7

    res_async = await reg.execute("echo", {"msg": "friday"})
    assert res_async.ok is True
    assert res_async.output == "FRIDAY"


@pytest.mark.anyio
async def test_workspace_read_blocks_secrets_and_reads_safe_files(tmp_path: Path):
    secret_env = tmp_path / ".env"
    secret_env.write_text("OPENROUTER_API_KEY=sk-secret-123\n")
    notes = tmp_path / "notes.txt"
    notes.write_text("line1\nline2\nline3\n")

    reg = build_default_registry(tmp_path)

    # Reading .env must be refused cleanly
    blocked = await reg.execute("read_file_snippet", {"path": str(secret_env)})
    assert blocked.ok is False
    assert "sk-secret-123" not in blocked.output

    # Reading normal file works
    ok_res = await reg.execute("read_file_snippet", {"path": str(notes), "start_line": 2, "max_lines": 2})
    assert ok_res.ok is True
    assert "line2" in ok_res.output
    assert "line3" in ok_res.output
    assert "line1" not in ok_res.output


@pytest.mark.anyio
async def test_default_registry_assigns_expected_risk_tiers(tmp_path: Path):
    reg = build_default_registry(tmp_path)
    assert reg.get_tier("list_directory") == ToolRiskTier.SAFE
    assert reg.get_tier("read_file_snippet") == ToolRiskTier.SAFE
    assert reg.get_tier("search_files") == ToolRiskTier.SAFE
    assert reg.get_tier("system_status") == ToolRiskTier.SAFE
    assert reg.get_tier("rea_teardown") == ToolRiskTier.SAFE
    assert reg.get_tier("run_shell") in (ToolRiskTier.CONFIRM, ToolRiskTier.DANGEROUS)
    assert reg.get_tier("write_file_content") == ToolRiskTier.CONFIRM
