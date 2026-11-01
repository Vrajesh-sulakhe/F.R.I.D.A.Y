"""
Mac App Launcher & Local System Tools for FRIDAY.
Allows FRIDAY to detect and open installed macOS applications,
launch local documents/files, reveal items in Finder, and preview files.
"""
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("FRIDAY.MacApps")

APP_DIRECTORIES = [
    Path("/Applications"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
]


class MacAppLauncher:
    @staticmethod
    def get_installed_apps() -> dict[str, str]:
        """Scan standard macOS application directories for installed .app bundles."""
        apps: dict[str, str] = {}
        for app_dir in APP_DIRECTORIES:
            if not app_dir.exists():
                continue
            try:
                for item in app_dir.iterdir():
                    if item.name.endswith(".app"):
                        app_name = item.name[:-4]  # Remove .app
                        apps[app_name.lower()] = app_name
            except Exception as e:
                logger.warning(f"Failed to scan {app_dir}: {e}")

        # Common built-in aliases
        aliases = {
            "calendar": "Calendar",
            "mail": "Mail",
            "notes": "Notes",
            "safari": "Safari",
            "chrome": "Google Chrome",
            "brave": "Brave Browser",
            "terminal": "Terminal",
            "canva": "Canva",
            "finder": "Finder",
            "settings": "System Settings",
            "system settings": "System Settings",
            "calculator": "Calculator",
            "messages": "Messages",
            "music": "Music",
            "spotify": "Spotify",
            "slack": "Slack",
            "figma": "Figma",
            "claude": "Claude",
            "chatgpt": "ChatGPT",
            "lm studio": "LM Studio",
            "vscode": "Visual Studio Code",
            "code": "Visual Studio Code",
        }
        for alias, target in aliases.items():
            if alias not in apps:
                apps[alias] = target

        return apps

    @staticmethod
    def open_app(app_name_query: str) -> tuple[bool, str, str]:
        """
        Open a specified application on macOS.
        Returns: (success: bool, resolved_app_name: str, message: str)
        """
        query = app_name_query.strip().lower()
        # Clean common prefixes like "open", "launch", "the"
        for prefix in ["open", "launch", "start", "run", "the"]:
            if query.startswith(prefix + " "):
                query = query[len(prefix) + 1:].strip()

        installed = MacAppLauncher.get_installed_apps()

        # Direct match or partial match
        resolved_name = installed.get(query)
        if not resolved_name:
            for k, v in installed.items():
                if query in k or k in query:
                    resolved_name = v
                    break

        if not resolved_name:
            resolved_name = app_name_query.strip().title()

        try:
            cmd = ["/usr/bin/open", "-a", resolved_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info(f"Successfully launched {resolved_name}")
                return True, resolved_name, f"Launched {resolved_name} successfully."
            else:
                err = result.stderr.strip() or "Unknown launch error"
                logger.warning(f"Failed to launch {resolved_name}: {err}")
                return False, resolved_name, f"Could not launch {resolved_name}: {err}"
        except Exception as e:
            logger.error(f"Error launching {resolved_name}: {e}")
            return False, resolved_name, str(e)

    @staticmethod
    def open_file_path(path_str: str) -> tuple[bool, str]:
        """Open any file or directory in its default macOS handler."""
        p = Path(path_str).expanduser()
        if not p.exists():
            return False, f"Item not found on your Mac: {path_str}"
        try:
            cmd = ["/usr/bin/open", str(p)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return True, f"Opened {p.name} on macOS."
            return False, res.stderr.strip() or "Failed to open file."
        except Exception as e:
            return False, str(e)

    @staticmethod
    def reveal_in_finder(path_str: str) -> tuple[bool, str]:
        """Reveal any file, app, or folder in macOS Finder."""
        p = Path(path_str).expanduser()
        if not p.exists():
            return False, f"Item not found on your Mac: {path_str}"
        try:
            cmd = ["/usr/bin/open", "-R", str(p)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return True, f"Revealed {p.name} in Finder."
            return False, res.stderr.strip() or "Failed to reveal in Finder."
        except Exception as e:
            return False, str(e)

    @staticmethod
    def read_file_preview(path_str: str, max_chars: int = 4000) -> tuple[bool, str]:
        """Read text content of local files for preview and speech."""
        p = Path(path_str).expanduser()
        if not p.exists():
            return False, f"File not found: {path_str}"
        if p.is_dir():
            items = [f.name for f in p.iterdir() if not f.name.startswith(".")]
            return True, f"Directory containing {len(items)} items: " + ", ".join(items[:20])

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
                if len(content) == max_chars:
                    content += "\n... [truncated]"
                return True, content
        except Exception as e:
            return False, f"Could not read file text: {e}"
