"""Tests for Phase 4: Persistent SQLite Semantic Memory & Living 3D Second Brain Graph."""
from pathlib import Path
from unittest.mock import patch

from src.agent.registry import ToolRegistry, ToolRiskTier
from src.second_brain.memory import MemoryStore, register_memory_tools
from src.second_brain.indexer import SecondBrainIndexer


def test_memory_store_crud_and_recall(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")

    mid1 = store.remember(
        topic="Coffee Preference",
        content="Sir prefers black espresso before 9 AM and green tea in the afternoon.",
        category="Preference",
        importance=5,
    )
    mid2 = store.remember(
        topic="Reaper Repo",
        content="AWS Hack-to-Ween cloud resource cleaner located in GitHub/Reaper.",
        category="Project",
        importance=4,
    )
    assert mid1 and mid2

    hits = store.recall("espresso tea")
    assert len(hits) >= 1
    assert "espresso" in hits[0]["content"]

    all_mems = store.list_recent(limit=10)
    assert len(all_mems) == 2

    deleted = store.forget(mid1)
    assert deleted is True
    assert len(store.list_recent(limit=10)) == 1


def test_memory_tools_and_second_brain_indexer_integration(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")
    store.remember("Deployment Port", "FRIDAY binds on localhost port 4719.", category="Architecture", importance=4)

    added_events = []
    reg = ToolRegistry()
    register_memory_tools(reg, store, on_memory_added=lambda item: added_events.append(item))

    assert reg.get_tier("memory_remember") == ToolRiskTier.SAFE
    assert reg.get_tier("memory_recall") == ToolRiskTier.SAFE

    graph = SecondBrainIndexer.scan_local_machine(memory_store=store)
    hub_names = [h["name"] for h in graph["hubs"]]
    assert "Memory Vault" in hub_names
    mem_nodes = [n for n in graph["nodes"] if n.get("hub") == "Memory Vault"]
    assert len(mem_nodes) == 1
    assert mem_nodes[0]["name"] == "Deployment Port"
