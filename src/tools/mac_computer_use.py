"""
macOS Computer Use, Accessibility UI Inspector, Clipboard & Notification tools for F.R.I.D.A.Y.
All mutating UI actions require human-in-the-loop Safety Gate confirmation.
"""
import asyncio
import logging
from typing import Any

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier

logger = logging.getLogger("FRIDAY.MacComputerUse")

_UI_TREE_SCRIPT = '''
tell application "System Events"
    set targetName to "{app_filter}"
    if targetName is "" then
        set targetProc to first application process whose frontmost is true
    else
        set targetProc to first application process whose name is targetName
    end if
    set procName to name of targetProc
    set outList to {{"App: " & procName}}
    try
        set win to front window of targetProc
        set end of outList to "Window: " & (name of win)
        try
            set btns to name of every button of win
            if (count of btns) > 0 then set end of outList to "Buttons: " & (items 1 thru (my minVal(count of btns, 12)) of btns as string)
        end try
        try
            set flds to description of every text field of win
            if (count of flds) > 0 then set end of outList to "Fields: " & (items 1 thru (my minVal(count of flds, 8)) of flds as string)
        end try
    end try
    return outList as string
end tell
on minVal(a, b)
    if a < b then return a
    return b
end minVal
'''

_SUPPORTED_KEYS = {
    "return": "return",
    "enter": "return",
    "escape": "escape",
    "esc": "escape",
    "tab": "tab",
    "space": "space",
}


async def _run_exec(cmd: list[str], stdin_text: str | None = None, timeout: float = 5.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    input_bytes = stdin_text.encode("utf-8") if stdin_text is not None else None
    stdout, stderr = await asyncio.wait_for(proc.communicate(input=input_bytes), timeout=timeout)
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def register_mac_computer_use_tools(registry: ToolRegistry) -> None:
    """Register macOS Accessibility, clipboard, notification, and UI action tools."""

    async def get_clipboard() -> ToolExecutionResult:
        rc, out, err = await _run_exec(["/usr/bin/pbpaste"])
        if rc != 0:
            return ToolExecutionResult(ok=False, output=err or "Failed to read macOS clipboard.")
        return ToolExecutionResult(ok=True, output=out[:3000] if out else "(clipboard empty)")

    async def set_clipboard(text: str) -> ToolExecutionResult:
        rc, _, err = await _run_exec(["/usr/bin/pbcopy"], stdin_text=text)
        if rc != 0:
            return ToolExecutionResult(ok=False, output=err or "Failed to write macOS clipboard.")
        return ToolExecutionResult(ok=True, output=f"Copied {len(text)} characters to macOS clipboard.")

    async def get_ui_tree(app_name: str = "") -> ToolExecutionResult:
        safe_app = _escape_applescript(app_name.strip())
        script = _UI_TREE_SCRIPT.format(app_filter=safe_app)
        rc, out, err = await _run_exec(["/usr/bin/osascript", "-e", script])
        if rc != 0:
            return ToolExecutionResult(
                ok=False,
                output=f"Unable to read Accessibility UI tree: {err or 'Grant Accessibility permission in System Settings.'}",
            )
        return ToolExecutionResult(ok=True, output=out or "No visible UI elements reported.")

    async def send_mac_notification(title: str, message: str) -> ToolExecutionResult:
        safe_t = _escape_applescript(title[:80])
        safe_m = _escape_applescript(message[:240])
        script = f'display notification "{safe_m}" with title "{safe_t}"'
        rc, _, err = await _run_exec(["/usr/bin/osascript", "-e", script])
        if rc != 0:
            return ToolExecutionResult(ok=False, output=err or "Failed to display notification.")
        return ToolExecutionResult(ok=True, output=f"Notification displayed: {title}")

    async def ui_action(action: str, target_or_text: str, app_name: str = "") -> ToolExecutionResult:
        act = action.strip().lower()
        safe_app = _escape_applescript(app_name.strip())
        safe_val = _escape_applescript(target_or_text)
        proc_prefix = f'tell application "{safe_app}" to activate\n' if safe_app else ""

        if act == "type_text":
            script = (
                f'{proc_prefix}tell application "System Events"\n'
                f'  keystroke "{safe_val}"\n'
                f"end tell"
            )
        elif act == "click_button":
            script = (
                f'{proc_prefix}tell application "System Events"\n'
                f'  tell (first application process whose frontmost is true)\n'
                f'    click button "{safe_val}" of front window\n'
                f"  end tell\n"
                f"end tell"
            )
        elif act == "press_key":
            key_name = _SUPPORTED_KEYS.get(target_or_text.strip().lower())
            if not key_name:
                return ToolExecutionResult(
                    ok=False,
                    output=f"Unsupported key '{target_or_text}'. Supported: {', '.join(sorted(_SUPPORTED_KEYS))}.",
                )
            script = f'{proc_prefix}tell application "System Events" to keystroke {key_name}'
        else:
            return ToolExecutionResult(
                ok=False,
                output=f"Unknown UI action '{action}'. Use 'click_button', 'type_text', or 'press_key'.",
            )

        rc, out, err = await _run_exec(["/usr/bin/osascript", "-e", script])
        if rc != 0:
            return ToolExecutionResult(ok=False, output=f"UI action failed: {err or 'Accessibility permission may be required.'}")
        return ToolExecutionResult(ok=True, output=out or f"Executed {act} cleanly.")

    registry.register(
        RegisteredTool(
            name="get_clipboard",
            description="Read the current text contents of the macOS clipboard.",
            parameters={"type": "object", "properties": {}},
            handler=get_clipboard,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="set_clipboard",
            description="Copy text onto the macOS clipboard.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to copy to clipboard."}},
                "required": ["text"],
            },
            handler=set_clipboard,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )
    registry.register(
        RegisteredTool(
            name="get_ui_tree",
            description="Inspect visible buttons, fields, and window title of the frontmost or named macOS app.",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Optional app name; defaults to frontmost app.", "default": ""}
                },
            },
            handler=get_ui_tree,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="send_mac_notification",
            description="Display a native macOS Notification Center alert.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Alert title."},
                    "message": {"type": "string", "description": "Notification body text."},
                },
                "required": ["title", "message"],
            },
            handler=send_mac_notification,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="ui_action",
            description="Perform a guarded macOS UI automation action (click_button, type_text, press_key) in the active window.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["click_button", "type_text", "press_key"]},
                    "target_or_text": {"type": "string", "description": "Button name, text to type, or key name."},
                    "app_name": {"type": "string", "description": "Optional target app to focus first.", "default": ""},
                },
                "required": ["action", "target_or_text"],
            },
            handler=ui_action,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )
