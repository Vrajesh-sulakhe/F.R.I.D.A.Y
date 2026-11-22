"""
FOCUS: Active macOS application & window context tracker and notification gating.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("FRIDAY.Vision.Focus")

_FOCUS_APPLESCRIPT = '''
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
    set winTitle to ""
    try
        set winTitle to name of front window of application process frontApp
    end try
    return frontApp & "|||" & winTitle
end tell
'''


@dataclass
class FocusContext:
    app_name: str = ""
    window_title: str = ""
    updated_at: float = 0.0


class FocusMonitor:
    """Detects active macOS workspace context and gates non-critical interruptions in FOCUS mode."""

    def __init__(self):
        self.enabled: bool = False
        self._cached_context: FocusContext = FocusContext()

    @staticmethod
    def parse_osascript_output(raw: str) -> FocusContext:
        cleaned = (raw or "").strip()
        if "|||" in cleaned:
            app, title = cleaned.split("|||", 1)
            return FocusContext(app_name=app.strip(), window_title=title.strip(), updated_at=time.time())
        return FocusContext(app_name=cleaned, window_title="", updated_at=time.time())

    def set_focus_mode(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def should_suppress_notification(self, priority: str = "normal") -> bool:
        """Suppress normal notifications while FOCUS mode is active; critical alerts still pass."""
        if not self.enabled:
            return False
        return priority.lower() != "critical"

    async def refresh_active_window(self) -> FocusContext:
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/osascript",
                "-e",
                _FOCUS_APPLESCRIPT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode == 0:
                self._cached_context = self.parse_osascript_output(stdout.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.debug(f"Active window probe unavailable: {e}")
        return self._cached_context

    def format_prompt_context(self) -> str:
        ctx = self._cached_context
        if not ctx.app_name:
            return ""
        mode_note = "FOCUS mode is ACTIVE (suppress distractions, keep responses crisp)." if self.enabled else ""
        win_part = f" (window: '{ctx.window_title}')" if ctx.window_title else ""
        return f"[Ambient Workspace Context] Frontmost macOS app: {ctx.app_name}{win_part}. {mode_note}".strip()
