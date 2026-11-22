"""
REFLEX: Proactive autonomous background watchers and alert queue for F.R.I.D.A.Y.
Respects FocusMonitor: non-critical alerts queue quietly while FOCUS mode is on
and flush once the user exits Focus mode.
"""
import asyncio
import inspect
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from src.vision.focus import FocusMonitor

logger = logging.getLogger("FRIDAY.Reflex")


@dataclass
class ReflexRule:
    id: str
    name: str
    kind: str  # "system_vitals" | "git_workspace" | "briefing"
    interval_seconds: int = 300
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    last_run_ts: float = 0.0


def load_reflex_rules(config_path: Path) -> list[ReflexRule]:
    if not config_path.exists():
        return []
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        raw_rules = data.get("reflexes", []) or []
        return [
            ReflexRule(
                id=str(r["id"]),
                name=str(r.get("name", r["id"])),
                kind=str(r.get("kind", "system_vitals")),
                interval_seconds=max(15, int(r.get("interval_seconds", 300))),
                enabled=bool(r.get("enabled", True)),
                params=dict(r.get("params") or {}),
            )
            for r in raw_rules
            if isinstance(r, dict) and r.get("id")
        ]
    except Exception as e:
        logger.warning(f"Failed to parse reflexes config {config_path}: {e}")
        return []


class ReflexDaemon:
    """Background proactive monitoring loop with FOCUS-mode alert gating."""

    def __init__(
        self,
        rules: list[ReflexRule] | None = None,
        focus_monitor: FocusMonitor | None = None,
        on_alert: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        project_root: Path | None = None,
        memory_store: Any = None,
    ):
        self.rules: list[ReflexRule] = list(rules or [])
        self.focus_monitor = focus_monitor
        self.on_alert = on_alert
        self.project_root = project_root or Path.cwd()
        self.memory_store = memory_store
        self.running: bool = False
        self.armed: bool = True
        self.queued_alerts: list[dict[str, Any]] = []
        self.recent_alerts: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self._last_git_dirty_reported: int | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="friday_reflex_daemon")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self.running:
            now = time.monotonic()
            for rule in self.rules:
                if not rule.enabled:
                    continue
                if now - rule.last_run_ts >= rule.interval_seconds:
                    rule.last_run_ts = now
                    try:
                        await self.trigger_rule(rule.id)
                    except Exception as e:
                        logger.debug(f"Reflex rule {rule.id} tick error: {e}")
            await asyncio.sleep(5.0)

    async def _deliver_or_queue(self, alert: dict[str, Any]) -> None:
        suppress = (
            self.focus_monitor is not None
            and self.focus_monitor.should_suppress_notification(alert.get("priority", "normal"))
        )
        if suppress:
            self.queued_alerts.append(alert)
            return

        self.recent_alerts = (self.recent_alerts + [alert])[-20:]
        if self.on_alert:
            res = self.on_alert(alert)
            if inspect.isawaitable(res):
                await res

    async def flush_queued(self) -> int:
        if not self.queued_alerts:
            return 0
        to_send = list(self.queued_alerts)
        self.queued_alerts.clear()
        for alert in to_send:
            await self._deliver_or_queue(alert)
        return len(to_send)

    async def _check_system_vitals(self, params: dict[str, Any]) -> dict[str, Any] | None:
        min_disk_gb = float(params.get("min_disk_free_gb", 5.0))
        max_load = float(params.get("max_load_1m", 8.0))
        min_batt = int(params.get("min_battery_pct", 15))

        disk = shutil.disk_usage(self.project_root)
        free_gb = disk.free / (1024 ** 3)
        if free_gb < min_disk_gb:
            return {
                "priority": "critical",
                "title": "Low Disk Space",
                "message": f"Only {free_gb:.1f} GB disk space remaining, sir.",
            }

        load_1m = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        if load_1m > max_load:
            return {
                "priority": "normal",
                "title": "Elevated CPU Load",
                "message": f"System 1-minute load average reached {load_1m:.2f}, sir.",
            }

        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/pmset", "-g", "batt",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            batt_txt = stdout.decode("utf-8", errors="ignore")
            m = re.search(r"(\d+)%;\s*(discharging|charging|charged)", batt_txt, re.IGNORECASE)
            if m and m.group(2).lower() == "discharging" and int(m.group(1)) <= min_batt:
                return {
                    "priority": "critical",
                    "title": "Battery Low",
                    "message": f"Power reserve is down to {m.group(1)}% and discharging, sir.",
                }
        except Exception:
            pass

        return None

    async def _check_git_workspace(self, params: dict[str, Any]) -> dict[str, Any] | None:
        repo = Path(params.get("repo_path") or self.project_root)
        if not (repo / ".git").exists():
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/git", "-C", str(repo), "status", "--short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            lines = [ln for ln in stdout.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
            threshold = int(params.get("dirty_threshold", 8))
            if len(lines) >= threshold and self._last_git_dirty_reported != len(lines):
                self._last_git_dirty_reported = len(lines)
                return {
                    "priority": "normal",
                    "title": "Workspace Drift",
                    "message": f"{repo.name} has {len(lines)} uncommitted paths pending review, sir.",
                }
        except Exception:
            pass
        return None

    async def build_briefing(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.project_root)
        free_gb = disk.free / (1024 ** 3)
        mem_count = len(self.memory_store.list_recent(limit=50)) if self.memory_store else 0
        focus_label = "Focus ON" if (self.focus_monitor and self.focus_monitor.enabled) else "Standard"
        return {
            "priority": "normal",
            "title": "Tactical Briefing",
            "message": f"All systems nominal, sir ({focus_label}). {free_gb:.1f} GB disk free and {mem_count} persisted Second Brain memories indexed.",
        }

    async def trigger_rule(self, rule_id: str) -> list[dict[str, Any]]:
        rule = next((r for r in self.rules if r.id == rule_id), None)
        if not rule:
            return []

        raw: dict[str, Any] | None = None
        if rule.kind == "system_vitals":
            raw = await self._check_system_vitals(rule.params)
        elif rule.kind == "git_workspace":
            raw = await self._check_git_workspace(rule.params)
        elif rule.kind == "briefing":
            raw = await self.build_briefing()

        if not raw:
            return []

        alert = {
            "type": "reflex_alert",
            "id": f"rfx_{uuid.uuid4().hex[:8]}",
            "reflex_id": rule.id,
            "priority": raw.get("priority", "normal"),
            "title": raw.get("title", rule.name),
            "message": raw.get("message", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._deliver_or_queue(alert)
        return [alert]

    def status(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "running": self.running,
            "queued_count": len(self.queued_alerts),
            "recent_alerts": list(self.recent_alerts[-5:]),
            "rules": [
                {
                    "id": r.id,
                    "name": r.name,
                    "kind": r.kind,
                    "interval_seconds": r.interval_seconds,
                    "enabled": r.enabled,
                }
                for r in self.rules
            ],
        }
