"""
Autonomous Multi-Step Mission Control for F.R.I.D.A.Y (Phase 6).
Persists long-horizon tasks into SQLite, executes them via AgentLoop,
and reports live step checkpoints back to the HUD.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier
from src.llm.base import ChatMessage
from src.second_brain.memory import MemoryStore


class MissionManager:
    """Manages persistent multi-step or recurring autonomous missions."""

    def __init__(self, memory_store: MemoryStore, agent_loop: Any = None):
        self.store = memory_store
        self.agent_loop = agent_loop

    def create_mission(self, title: str, goal: str, interval_seconds: int = 0) -> dict[str, Any]:
        mission_id = f"msn_{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.store._connect() as conn:
            conn.execute(
                """
                INSERT INTO missions (id, title, goal, status, interval_seconds, last_run_at, last_summary, steps_json, created_at)
                VALUES (?, ?, ?, 'pending', ?, NULL, NULL, '[]', ?)
                """,
                (mission_id, title.strip(), goal.strip(), max(0, int(interval_seconds)), now_iso),
            )
            conn.commit()
        return self.get_mission(mission_id) or {}

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["steps"] = json.loads(d.get("steps_json") or "[]")
        except Exception:
            d["steps"] = []
        return d

    def list_missions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM missions ORDER BY created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["steps"] = json.loads(d.get("steps_json") or "[]")
            except Exception:
                d["steps"] = []
            out.append(d)
        return out

    def cancel_mission(self, mission_id: str) -> bool:
        with self.store._connect() as conn:
            cur = conn.execute("UPDATE missions SET status = 'canceled' WHERE id = ?", (mission_id,))
            conn.commit()
            return cur.rowcount > 0

    async def run_mission(
        self,
        mission_id: str,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        mission = self.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found.")
        if not self.agent_loop:
            raise RuntimeError("AgentLoop not attached to MissionManager.")

        now_iso = datetime.now(timezone.utc).isoformat()
        with self.store._connect() as conn:
            conn.execute("UPDATE missions SET status = 'running', last_run_at = ? WHERE id = ?", (now_iso, mission_id))
            conn.commit()

        steps_log: list[str] = []

        async def _capture_emit(ev: dict[str, Any]) -> None:
            if ev.get("type") == "tool_start":
                steps_log.append(f"Called {ev.get('tool_name')}")
            if emit:
                await emit(ev)

        try:
            prompt = (
                f"Execute autonomous mission '{mission['title']}'. Goal:\n{mission['goal']}\n\n"
                "Use only SAFE inspection/memory tools unless essential, verify findings accurately, "
                "and summarize concisely."
            )
            result = await self.agent_loop.run(
                messages=[ChatMessage(role="user", content=prompt)],
                emit=_capture_emit,
            )
            status = "completed"
            summary = result.reply
        except Exception as e:
            status = "failed"
            summary = f"Mission error: {e}"

        done_iso = datetime.now(timezone.utc).isoformat()
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE missions
                SET status = ?, last_run_at = ?, last_summary = ?, steps_json = ?
                WHERE id = ?
                """,
                (status, done_iso, summary, json.dumps(steps_log), mission_id),
            )
            conn.commit()

        return self.get_mission(mission_id) or {}


def register_mission_tools(registry: ToolRegistry, mission_manager: MissionManager) -> None:
    """Register mission creation, inspection, and execution tools."""

    def create_mission(title: str, goal: str, interval_seconds: int = 0) -> ToolExecutionResult:
        m = mission_manager.create_mission(title=title, goal=goal, interval_seconds=interval_seconds)
        return ToolExecutionResult(
            ok=True,
            output=f"Created mission '{m['title']}' (id={m['id']}, status={m['status']}).",
            data=m,
        )

    def list_missions() -> ToolExecutionResult:
        ms = mission_manager.list_missions()
        if not ms:
            return ToolExecutionResult(ok=True, output="No missions queued or recorded yet.")
        lines = [f"[{m['id']}] {m['title']} — {m['status']} ({(m.get('last_summary') or '')[:80]})" for m in ms]
        return ToolExecutionResult(ok=True, output="\n".join(lines), data={"missions": ms})

    async def run_mission(mission_id: str) -> ToolExecutionResult:
        m = await mission_manager.run_mission(mission_id)
        return ToolExecutionResult(
            ok=(m.get("status") == "completed"),
            output=f"Mission {mission_id} -> {m.get('status')}: {m.get('last_summary')}",
            data=m,
        )

    registry.register(
        RegisteredTool(
            name="create_mission",
            description="Create and save a persistent multi-step or recurring autonomous mission.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short mission title."},
                    "goal": {"type": "string", "description": "Objective and acceptance criteria."},
                    "interval_seconds": {"type": "integer", "description": "Optional recurring cadence in seconds (0 = one-shot).", "default": 0},
                },
                "required": ["title", "goal"],
            },
            handler=create_mission,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="list_missions",
            description="List saved autonomous missions and their execution status.",
            parameters={"type": "object", "properties": {}},
            handler=list_missions,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="run_mission",
            description="Execute a saved autonomous mission through the agent loop.",
            parameters={
                "type": "object",
                "properties": {"mission_id": {"type": "string", "description": "Mission ID to run."}},
                "required": ["mission_id"],
            },
            handler=run_mission,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )
