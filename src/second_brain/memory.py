"""
Persistent SQLite Semantic & Episodic Memory Store for F.R.I.D.A.Y.
Backed by data/memory.db, synced into the 3D Second Brain galaxy.
"""
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier


class MemoryStore:
    """SQLite-backed durable memory & mission storage."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Fact',
                    content TEXT NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 3,
                    source TEXT NOT NULL DEFAULT 'conversation',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    interval_seconds INTEGER NOT NULL DEFAULT 0,
                    last_run_at TEXT,
                    last_summary TEXT,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def remember(
        self,
        topic: str,
        content: str,
        category: str = "Fact",
        importance: int = 3,
        source: str = "conversation",
    ) -> str:
        mem_id = f"mem_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        clamped_imp = max(1, min(5, int(importance)))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, topic, category, content, importance, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mem_id, topic.strip(), category.strip() or "Fact", content.strip(), clamped_imp, source, now_iso),
            )
            conn.commit()
        return mem_id

    def recall(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        tokens = [t for t in re.findall(r"[a-z0-9_]+", (query or "").lower()) if len(t) >= 2]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, topic, category, content, importance, source, created_at FROM memories ORDER BY created_at DESC LIMIT 200"
            ).fetchall()

        scored: list[tuple[int, int, str, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            haystack = f"{item['topic']} {item['category']} {item['content']}".lower()
            if not tokens:
                match_score = 1
            else:
                match_score = sum(3 if t in item["topic"].lower() else (1 if t in haystack else 0) for t in tokens)
            if tokens and match_score == 0:
                continue
            scored.append((match_score, item["importance"], item["created_at"], item))

        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return [x[3] for x in scored[: max(1, limit)]]

    def list_recent(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, topic, category, content, importance, source, created_at FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def forget(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cur.rowcount > 0

    def format_prompt_memories(self, query: str, limit: int = 3) -> str:
        hits = self.recall(query, limit=limit)
        if not hits:
            return ""
        lines = ["[Second Brain Recalled Memories]"]
        for m in hits:
            lines.append(f"- ({m['category']}) {m['topic']}: {m['content']}")
        return "\n".join(lines)


def register_memory_tools(
    registry: ToolRegistry,
    store: MemoryStore,
    on_memory_added: Callable[[dict[str, Any]], Any] | None = None,
) -> None:
    """Register semantic memory read/write tools into ToolRegistry."""

    def memory_remember(
        topic: str,
        content: str,
        category: str = "Fact",
        importance: int = 3,
    ) -> ToolExecutionResult:
        mem_id = store.remember(topic=topic, content=content, category=category, importance=importance)
        mem_obj = {
            "id": mem_id,
            "topic": topic.strip(),
            "category": category.strip() or "Fact",
            "content": content.strip(),
            "importance": importance,
        }
        if on_memory_added:
            try:
                on_memory_added(mem_obj)
            except Exception:
                pass
        return ToolExecutionResult(
            ok=True,
            output=f"Stored memory '{topic}' ({category}, id={mem_id}) in your Second Brain.",
            data=mem_obj,
        )

    def memory_recall(query: str, limit: int = 6) -> ToolExecutionResult:
        hits = store.recall(query, limit=limit)
        if not hits:
            return ToolExecutionResult(ok=True, output=f"No memories found matching '{query}'.", data={"hits": []})
        lines = [f"[{m['id']}] ({m['category']}) {m['topic']}: {m['content']}" for m in hits]
        return ToolExecutionResult(ok=True, output="\n".join(lines), data={"hits": hits})

    registry.register(
        RegisteredTool(
            name="memory_remember",
            description="Persist a durable fact, decision, preference, or insight into F.R.I.D.A.Y's SQLite Second Brain.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Short title/topic for the memory node."},
                    "content": {"type": "string", "description": "Detailed knowledge or preference to store."},
                    "category": {"type": "string", "description": "Category e.g. Fact, Preference, Project, Decision.", "default": "Fact"},
                    "importance": {"type": "integer", "description": "1 (low) to 5 (critical).", "default": 3},
                },
                "required": ["topic", "content"],
            },
            handler=memory_remember,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="memory_recall",
            description="Search F.R.I.D.A.Y's persistent Second Brain memory database by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords or topic to recall."},
                    "limit": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
            handler=memory_recall,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
