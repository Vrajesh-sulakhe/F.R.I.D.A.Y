"""
Core local workspace, system telemetry, shell, and macOS tools for F.R.I.D.A.Y.
Wraps native tools into ToolRegistry with explicit secret protection and risk tiers.
"""
import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier
from src.tools.mac_apps import MacAppLauncher
from src.tools.rea import REATeardownEngine

if TYPE_CHECKING:
    from src.llm.router import ModelRouter
    from src.vision.focus import FocusMonitor
    from src.vision.screen import ScreenVisionEngine

_SENSITIVE_NAMES = {".env", ".local.env", "credentials.json", "id_rsa", "id_ed25519"}
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12")
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


def _is_sensitive_path(path: Path) -> bool:
    name_lower = path.name.lower()
    if name_lower in _SENSITIVE_NAMES or name_lower.startswith(".env."):
        return True
    if any(name_lower.endswith(sfx) for sfx in _SENSITIVE_SUFFIXES):
        return True
    if ".git" in path.parts or ".ssh" in path.parts:
        return True
    return False


def _resolve_target(path_str: str, project_root: Path) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = project_root / p
    return p.resolve()


def build_default_registry(
    project_root: Path,
    screen_engine: "ScreenVisionEngine | None" = None,
    focus_monitor: "FocusMonitor | None" = None,
    router: "ModelRouter | None" = None,
) -> ToolRegistry:
    """Create a ToolRegistry populated with F.R.I.D.A.Y.'s core workspace & macOS tools."""
    registry = ToolRegistry()
    root = project_root.resolve()

    def list_directory(path: str = ".") -> ToolExecutionResult:
        target = _resolve_target(path, root)
        if not target.exists():
            return ToolExecutionResult(ok=False, output=f"Path does not exist: {target}")
        if not target.is_dir():
            return ToolExecutionResult(ok=False, output=f"Not a directory: {target}")

        entries: list[str] = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name in _SKIP_DIRS or _is_sensitive_path(item):
                    continue
                marker = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{marker}")
                if len(entries) >= 80:
                    entries.append("... (truncated at 80 entries)")
                    break
        except Exception as e:
            return ToolExecutionResult(ok=False, output=f"Failed to list {target}: {e}")

        return ToolExecutionResult(
            ok=True,
            output="\n".join(entries) if entries else "(empty directory)",
            data={"path": str(target), "count": len(entries)},
        )

    def read_file_snippet(path: str, start_line: int = 1, max_lines: int = 120) -> ToolExecutionResult:
        target = _resolve_target(path, root)
        if _is_sensitive_path(target):
            return ToolExecutionResult(ok=False, output=f"Access denied to sensitive file: {target.name}")
        if not target.exists() or not target.is_file():
            return ToolExecutionResult(ok=False, output=f"File not found: {target}")

        start = max(1, int(start_line))
        limit = max(1, min(int(max_lines), 300))
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception as e:
            return ToolExecutionResult(ok=False, output=f"Could not read {target}: {e}")

        slice_lines = all_lines[start - 1 : start - 1 + limit]
        numbered = [f"{idx}: {line.rstrip()}" for idx, line in enumerate(slice_lines, start=start)]
        return ToolExecutionResult(
            ok=True,
            output="\n".join(numbered) if numbered else "(empty selection)",
            data={"path": str(target), "total_lines": len(all_lines)},
        )

    def search_files(pattern: str, directory: str = ".") -> ToolExecutionResult:
        target = _resolve_target(directory, root)
        if not target.exists() or not target.is_dir():
            return ToolExecutionResult(ok=False, output=f"Invalid search directory: {target}")

        pat = pattern.lower().strip()
        if not pat:
            return ToolExecutionResult(ok=False, output="Search pattern cannot be empty.")

        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".git")]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if _is_sensitive_path(fpath):
                    continue
                rel = str(fpath.relative_to(target)) if fpath.is_relative_to(target) else str(fpath)
                if pat in fname.lower() or pat in rel.lower():
                    matches.append(f"FILE {rel}")
                    if len(matches) >= 40:
                        break
            if len(matches) >= 40:
                break

        return ToolExecutionResult(
            ok=True,
            output="\n".join(matches) if matches else f"No files matched '{pattern}' under {target}.",
            data={"matches": matches},
        )

    def system_status() -> ToolExecutionResult:
        usage = shutil.disk_usage(root)
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        summary = (
            f"OS: {platform.system()} {platform.release()} ({platform.machine()}) | "
            f"Python: {platform.python_version()} | "
            f"Load (1m/5m/15m): {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f} | "
            f"Disk Free: {usage.free // (1024 ** 3)} GB / {usage.total // (1024 ** 3)} GB"
        )
        return ToolExecutionResult(
            ok=True,
            output=summary,
            data={
                "os": platform.system(),
                "machine": platform.machine(),
                "load_avg": list(load_avg),
                "disk_free_gb": round(usage.free / (1024 ** 3), 2),
            },
        )

    def list_mac_apps() -> ToolExecutionResult:
        apps = sorted(set(MacAppLauncher.get_installed_apps().values()))
        return ToolExecutionResult(
            ok=True,
            output=", ".join(apps[:80]),
            data={"count": len(apps), "apps": apps},
        )

    def open_mac_app(app_name: str) -> ToolExecutionResult:
        success, resolved, msg = MacAppLauncher.open_app(app_name)
        return ToolExecutionResult(ok=success, output=msg, data={"app_name": resolved})

    async def rea_teardown(target: str, mode: str = "auto") -> ToolExecutionResult:
        res = await REATeardownEngine.teardown(target, mode=mode)
        summary = res.get("spoken_summary") or f"Teardown of {target} complete."
        dossier = res.get("dossier") or ""
        combined = f"{summary}\n\n{dossier[:2000]}" if dossier else summary
        return ToolExecutionResult(
            ok=True,
            output=combined,
            data={
                "target": target,
                "type": res.get("type"),
                "dossier": dossier,
                "snapshot_url": res.get("snapshot_url"),
            },
        )

    def write_file_content(path: str, content: str, append: bool = False) -> ToolExecutionResult:
        target = _resolve_target(path, root)
        if _is_sensitive_path(target):
            return ToolExecutionResult(ok=False, output=f"Refusing to modify sensitive file: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        return ToolExecutionResult(
            ok=True,
            output=f"Wrote {len(content)} characters to {target}.",
            data={"path": str(target), "bytes": len(content.encode("utf-8"))},
            artifacts=[str(target)],
        )

    async def run_shell(command: str, cwd: str | None = None) -> ToolExecutionResult:
        work_dir = _resolve_target(cwd, root) if cwd else root
        if not work_dir.exists():
            return ToolExecutionResult(ok=False, output=f"Working directory not found: {work_dir}")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolExecutionResult(ok=False, output="Shell command timed out after 15s.")

        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()
        combined = "\n".join(part for part in (out_text, f"[stderr]\n{err_text}" if err_text else "") if part)
        if len(combined) > 3500:
            combined = combined[:3500] + "\n... [truncated]"

        return ToolExecutionResult(
            ok=(proc.returncode == 0),
            output=combined or f"(exit code {proc.returncode})",
            data={"returncode": proc.returncode, "cwd": str(work_dir)},
        )

    # Register SAFE tools
    registry.register(
        RegisteredTool(
            name="list_directory",
            description="List files and subdirectories in a local directory.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path (relative to workspace or absolute)."}},
            },
            handler=list_directory,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="read_file_snippet",
            description="Read a line range from a local text/code file (blocks secrets like .env).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read."},
                    "start_line": {"type": "integer", "description": "1-based start line.", "default": 1},
                    "max_lines": {"type": "integer", "description": "Number of lines to read (max 300).", "default": 120},
                },
                "required": ["path"],
            },
            handler=read_file_snippet,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="search_files",
            description="Search filenames and relative paths under a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Substring to match in file path or name."},
                    "directory": {"type": "string", "description": "Directory root to search.", "default": "."},
                },
                "required": ["pattern"],
            },
            handler=search_files,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="system_status",
            description="Inspect local macOS hardware load, OS info, and disk space.",
            parameters={"type": "object", "properties": {}},
            handler=system_status,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="list_mac_apps",
            description="List installed macOS applications available to launch.",
            parameters={"type": "object", "properties": {}},
            handler=list_mac_apps,
            risk_tier=ToolRiskTier.SAFE,
        )
    )
    registry.register(
        RegisteredTool(
            name="rea_teardown",
            description="Reverse engineer or analyze a website URL, macOS app, codebase, or file.",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Domain, URL, app name, or local path."},
                    "mode": {"type": "string", "enum": ["auto", "web", "app", "codebase", "file"], "default": "auto"},
                },
                "required": ["target"],
            },
            handler=rea_teardown,
            risk_tier=ToolRiskTier.SAFE,
        )
    )

    # Register CONFIRM tools (gated by HUD / voice approval)
    registry.register(
        RegisteredTool(
            name="open_mac_app",
            description="Launch an installed macOS application.",
            parameters={
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "Application name (e.g. Safari, Canva, Terminal)."}},
                "required": ["app_name"],
            },
            handler=open_mac_app,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )
    registry.register(
        RegisteredTool(
            name="write_file_content",
            description="Write or append text to a file on disk. Requires user confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path."},
                    "content": {"type": "string", "description": "Text content to write."},
                    "append": {"type": "boolean", "description": "Append instead of overwrite.", "default": False},
                },
                "required": ["path", "content"],
            },
            handler=write_file_content,
            risk_tier=ToolRiskTier.CONFIRM,
        )
    )
    registry.register(
        RegisteredTool(
            name="run_shell",
            description="Execute a shell command on this Mac. Requires explicit user approval.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "cwd": {"type": "string", "description": "Optional working directory."},
                },
                "required": ["command"],
            },
            handler=run_shell,
            risk_tier=ToolRiskTier.DANGEROUS,
        )
    )

    if screen_engine is not None:
        async def capture_screen(question: str = "Describe what is currently visible on the user's screen, including active windows, errors, or key text.") -> ToolExecutionResult:
            attachment = await screen_engine.capture_now(label="screen_tool")
            if not attachment:
                return ToolExecutionResult(
                    ok=False,
                    output=f"Could not capture macOS screen: {screen_engine.last_error or 'Screen Recording permission may be required.'}",
                )
            if router is not None:
                vision_out = await router.inspect_images([attachment], prompt=question)
                if vision_out:
                    desc, v_prov, v_model = vision_out
                    return ToolExecutionResult(
                        ok=True,
                        output=f"[Screen Vision via {v_prov} ({v_model})]\n{desc}",
                        data={"vision_provider": v_prov, "vision_model": v_model},
                    )
            return ToolExecutionResult(
                ok=True,
                output="Screen captured and buffered, but no vision-capable model is currently configured for your API keys to analyze pixels.",
            )

        registry.register(
            RegisteredTool(
                name="capture_screen",
                description="Capture the current macOS screen and inspect what is on display.",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Specific visual focus question for the screen analysis."}
                    },
                },
                handler=capture_screen,
                risk_tier=ToolRiskTier.SAFE,
            )
        )

    if focus_monitor is not None:
        async def get_active_window() -> ToolExecutionResult:
            ctx = await focus_monitor.refresh_active_window()
            if not ctx.app_name:
                return ToolExecutionResult(ok=False, output="Unable to query frontmost macOS window (Accessibility permission may be needed).")
            return ToolExecutionResult(
                ok=True,
                output=f"Frontmost App: {ctx.app_name} | Window: {ctx.window_title or '(untitled)'} | Focus Mode: {'on' if focus_monitor.enabled else 'off'}",
                data={"app_name": ctx.app_name, "window_title": ctx.window_title, "focus_enabled": focus_monitor.enabled},
            )

        registry.register(
            RegisteredTool(
                name="get_active_window",
                description="Inspect the currently focused macOS application and window title.",
                parameters={"type": "object", "properties": {}},
                handler=get_active_window,
                risk_tier=ToolRiskTier.SAFE,
            )
        )

    from src.tools.mac_computer_use import register_mac_computer_use_tools
    register_mac_computer_use_tools(registry)

    return registry
