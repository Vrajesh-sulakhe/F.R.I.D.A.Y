"""Tests for Phase 5 (REFLEX Daemons + FOCUS suppression) & Phase 6 (Missions + Voice Approval)."""
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from src.agent.registry import ToolExecutionResult, ToolRegistry, ToolRiskTier
from src.llm.base import ChatResponse, TokenUsage
from src.second_brain.memory import MemoryStore
from src.vision.focus import FocusMonitor
from src.reflex.daemon import ReflexDaemon, ReflexRule
from src.agent.missions import MissionManager, register_mission_tools


@pytest.mark.anyio
async def test_reflex_daemon_queues_normal_alerts_in_focus_and_flushes_on_exit():
    focus = FocusMonitor()
    focus.set_focus_mode(True)

    delivered = []

    async def on_alert(alert):
        delivered.append(alert)

    daemon = ReflexDaemon(
        rules=[
            ReflexRule(id="vitals", name="Vitals Check", kind="system_vitals", interval_seconds=60, enabled=True),
        ],
        focus_monitor=focus,
        on_alert=on_alert,
    )

    with patch.object(
        daemon,
        "_check_system_vitals",
        new=AsyncMock(return_value={"priority": "normal", "title": "System Load", "message": "Load spike 9.2"}),
    ):
        res = await daemon.trigger_rule("vitals")
        assert len(res) == 1
        # Suppressed while FOCUS is on -> queued, not delivered yet
        assert len(delivered) == 0
        assert len(daemon.queued_alerts) == 1

        # Critical alert bypasses FOCUS suppression
        with patch.object(
            daemon,
            "_check_system_vitals",
            new=AsyncMock(return_value={"priority": "critical", "title": "Battery Critical", "message": "Battery at 8%"}),
        ):
            await daemon.trigger_rule("vitals")
            assert len(delivered) == 1
            assert delivered[0]["priority"] == "critical"

        # Turning FOCUS off flushes queued normal alerts
        focus.set_focus_mode(False)
        await daemon.flush_queued()
        assert len(delivered) == 2
        assert len(daemon.queued_alerts) == 0


@pytest.mark.anyio
async def test_mission_manager_persists_and_executes_mission(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")

    class FakeLoop:
        async def run(self, messages, emit=None, approval_handler=None):
            from src.agent.loop import AgentRunResult
            return AgentRunResult(
                reply="Mission step complete: workspace clean.",
                provider="Mock",
                model="mock-1",
                steps=2,
                usage=TokenUsage(total_tokens=30),
            )

    mgr = MissionManager(store, agent_loop=FakeLoop())
    reg = ToolRegistry()
    register_mission_tools(reg, mgr)

    assert reg.get_tier("list_missions") == ToolRiskTier.SAFE
    assert reg.get_tier("create_mission") == ToolRiskTier.SAFE
    assert reg.get_tier("run_mission") == ToolRiskTier.CONFIRM

    m = mgr.create_mission(title="Health Check", goal="Check repo and system load.", interval_seconds=0)
    assert m["status"] == "pending"

    done = await mgr.run_mission(m["id"])
    assert done["status"] == "completed"
    assert "workspace clean" in done["last_summary"]

    listed = mgr.list_missions()
    assert len(listed) == 1
    assert listed[0]["id"] == m["id"]
