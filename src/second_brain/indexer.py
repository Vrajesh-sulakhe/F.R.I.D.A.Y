"""
Second Brain Indexer for FRIDAY:
Deep scanner for real local files, repositories, and applications on the user's Mac.
Constructs an interconnected 3D galaxy graph of the user's personal machine and account.
"""
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

logger = logging.getLogger("FRIDAY.SecondBrain")

HOME_DIR = Path.home()

# Scan targets representing the user's Mac system and account
SCAN_TARGETS = [
    {
        "id": "hub_apps",
        "name": "Applications",
        "path": Path("/Applications"),
        "category": "Applications",
        "color": 0x38bdf8,  # Electric Sky Blue
        "pos": (-180, 70, -70),
        "is_app_dir": True,
        "max_items": 45,
    },
    {
        "id": "hub_account_apps",
        "name": "Account Apps",
        "path": HOME_DIR / "Applications",
        "category": "Applications",
        "color": 0x06b6d4,  # Cyan
        "pos": (-140, 160, 60),
        "is_app_dir": True,
        "max_items": 25,
    },
    {
        "id": "hub_system_utils",
        "name": "System Utilities",
        "path": Path("/System/Applications"),
        "category": "Utilities",
        "color": 0xef4444,  # Coral Red
        "pos": (-240, -40, 50),
        "is_app_dir": True,
        "max_items": 30,
    },
    {
        "id": "hub_github",
        "name": "GitHub Projects",
        "path": HOME_DIR / "Documents" / "GitHub",
        "category": "Projects",
        "color": 0x10b981,  # Emerald Green
        "pos": (180, 80, -90),
        "deep_scan": True,
        "max_items": 35,
    },
    {
        "id": "hub_coding",
        "name": "Coding Workspace",
        "path": HOME_DIR / "coding",
        "category": "Projects",
        "color": 0x60a5fa,  # Royal Blue
        "pos": (140, -110, 110),
        "deep_scan": True,
        "max_items": 40,
    },
    {
        "id": "hub_downloads",
        "name": "Downloads",
        "path": HOME_DIR / "Downloads",
        "category": "Downloads",
        "color": 0xf97316,  # Warm Orange
        "pos": (70, 170, 80),
        "max_items": 45,
    },
    {
        "id": "hub_documents",
        "name": "Documents & Notes",
        "path": HOME_DIR / "Documents",
        "category": "Documents",
        "color": 0xfacc15,  # Amber Yellow
        "pos": (-50, -170, -90),
        "max_items": 30,
    },
    {
        "id": "hub_desktop",
        "name": "Desktop Items",
        "path": HOME_DIR / "Desktop",
        "category": "Desktop",
        "color": 0xec4899,  # Magenta
        "pos": (220, 20, 70),
        "max_items": 35,
    },
    {
        "id": "hub_friday",
        "name": "FRIDAY Core",
        "path": Path.cwd(),
        "category": "Brain",
        "color": 0xa855f7,  # Electric Violet
        "pos": (0, 0, 0),
        "deep_scan": True,
        "max_items": 25,
    },
]

# File category classifier by extension
EXT_CATEGORIES = {
    # Code
    ".py": ("Code", "Python Script"),
    ".js": ("Code", "JavaScript File"),
    ".ts": ("Code", "TypeScript File"),
    ".html": ("Code", "HTML Document"),
    ".css": ("Code", "CSS Stylesheet"),
    ".sh": ("Code", "Shell Script"),
    ".java": ("Code", "Java Source"),
    ".c": ("Code", "C Source"),
    ".cpp": ("Code", "C++ Source"),
    ".rs": ("Code", "Rust File"),
    ".go": ("Code", "Go File"),
    ".swift": ("Code", "Swift Source"),
    ".ipynb": ("Code", "Jupyter Notebook"),

    # Documents & Reading
    ".pdf": ("Documents", "PDF Document"),
    ".docx": ("Documents", "Word Document"),
    ".doc": ("Documents", "Word Document"),
    ".rtf": ("Documents", "Rich Text Document"),

    # Presentations
    ".pptx": ("Presentations", "PowerPoint Presentation"),
    ".ppt": ("Presentations", "PowerPoint Presentation"),
    ".key": ("Presentations", "Keynote Presentation"),

    # Notes & Documentation
    ".md": ("Notes", "Markdown Note"),
    ".txt": ("Notes", "Text File"),
    ".org": ("Notes", "Org Document"),

    # Data
    ".json": ("Data", "JSON Data"),
    ".csv": ("Data", "CSV Spreadsheet"),
    ".tsv": ("Data", "TSV Data"),
    ".sql": ("Data", "SQL Database Script"),
    ".xml": ("Data", "XML Data"),

    # Config
    ".yaml": ("Config", "YAML Config"),
    ".yml": ("Config", "YAML Config"),
    ".toml": ("Config", "TOML Config"),
    ".ini": ("Config", "Config File"),
    ".env": ("Config", "Environment Config"),

    # Media
    ".png": ("Media", "PNG Image"),
    ".jpg": ("Media", "JPEG Image"),
    ".jpeg": ("Media", "JPEG Image"),
    ".webp": ("Media", "WebP Image"),
    ".svg": ("Media", "Vector Image"),
    ".mp4": ("Media", "Video File"),
    ".mov": ("Media", "QuickTime Video"),
    ".mp3": ("Media", "Audio File"),
    ".wav": ("Media", "Audio File"),

    # Archives
    ".zip": ("Archives", "ZIP Archive"),
    ".dmg": ("Archives", "Apple Disk Image"),
    ".tar": ("Archives", "TAR Archive"),
    ".gz": ("Archives", "GZ Archive"),
    ".pkg": ("Archives", "macOS Package"),
}

CATEGORY_COLORS = {
    "Applications": 0x38bdf8,
    "Projects": 0x10b981,
    "Code": 0x60a5fa,
    "Documents": 0xf97316,
    "Presentations": 0xf43f5e,
    "Notes": 0xfacc15,
    "Data": 0xa855f7,
    "Config": 0x34d399,
    "Media": 0xec4899,
    "Utilities": 0xef4444,
    "Archives": 0x8b5cf6,
    "Downloads": 0xf97316,
    "Desktop": 0xec4899,
    "Brain": 0xa855f7,
    "Files": 0x94a3b8,
}


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class SecondBrainIndexer:
    @staticmethod
    def scan_local_machine(memory_store: Any = None, mcp_manager: Any = None) -> dict[str, Any]:
        """
        Scans local directories, installed applications, SQLite memories, and MCP bridges on macOS.
        Builds a comprehensive, interconnected 3D galaxy graph of the user's machine and Second Brain.
        """
        hubs_out = []
        nodes_out = []
        edges_out = []
        category_counts: dict[str, int] = {}

        for target in SCAN_TARGETS:
            path: Path = target["path"]
            if not path.exists():
                continue

            hub_name = target["name"]
            hub_id = target["id"]
            default_cat = target["category"]
            color = target["color"]
            pos = target["pos"]
            is_app_dir = target.get("is_app_dir", False)
            deep_scan = target.get("deep_scan", False)
            max_items = target.get("max_items", 35)

            child_nodes = []
            try:
                # Read items in target directory
                raw_items = list(path.iterdir())
                # Prioritize: for apps, only .app; for others, skip dotfiles except .env
                filtered_items = []
                for item in raw_items:
                    if item.name.startswith(".") and item.name not in [".env", ".gitignore"]:
                        continue
                    if item.name in ["node_modules", "__pycache__", ".git", ".venv", "env", "vendor"]:
                        continue
                    if is_app_dir and not item.name.endswith(".app"):
                        continue
                    filtered_items.append(item)

                # Sort by modification time (most recent first) for files/downloads/desktop,
                # or alphabetically for apps
                if is_app_dir:
                    filtered_items.sort(key=lambda p: p.name.lower())
                else:
                    try:
                        filtered_items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    except Exception:
                        filtered_items.sort(key=lambda p: p.name.lower())

                count = 0
                for item in filtered_items:
                    is_dir = item.is_dir()
                    is_app = item.name.endswith(".app")
                    ext = item.suffix.lower()

                    if is_app:
                        cat = "Applications" if hub_name != "System Utilities" else "Utilities"
                        type_label = "macOS Application"
                        display_name = item.name[:-4]  # Remove .app
                    elif is_dir:
                        cat = "Projects"
                        type_label = "Folder / Project"
                        display_name = item.name
                    else:
                        cat, type_label = EXT_CATEGORIES.get(ext, ("Files", "Local File"))
                        display_name = item.name

                    # Increment category count
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                    # File stats
                    size_bytes = 0
                    mtime_str = "Unknown"
                    try:
                        stat = item.stat()
                        size_bytes = stat.st_size if not is_dir else 0
                        mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y")
                    except Exception:
                        pass

                    size_human = _format_size(size_bytes) if not is_dir else "Folder"

                    # Generate Jarvis commentary
                    if is_app:
                        summary = f"Installed macOS application at {item}. Ready for instant voice launching, sir."
                    elif is_dir:
                        summary = f"Local directory and project workspace at {item}. Last modified {mtime_str}."
                    elif cat == "Documents" or cat == "Presentations":
                        summary = f"{type_label} ({size_human}) located in {path.name}. Ready for review or preview, sir."
                    elif cat == "Code" or cat == "Notes":
                        summary = f"{type_label} ({size_human}) on your Mac. Indexed in your Second Brain."
                    else:
                        summary = f"Local item ({size_human}) in {path.name}. Last modified {mtime_str}."

                    node_id = f"node_{hub_id}_{count}"
                    node_obj = {
                        "id": node_id,
                        "name": display_name,
                        "type": type_label,
                        "category": cat,
                        "path": str(item),
                        "hub": hub_name,
                        "hub_id": hub_id,
                        "is_app": is_app,
                        "is_dir": is_dir,
                        "size_bytes": size_bytes,
                        "size_human": size_human,
                        "mtime": mtime_str,
                        "summary": summary,
                        "is_text_readable": ext in [".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sh", ".env"],
                    }

                    child_nodes.append(node_obj)
                    nodes_out.append(node_obj)
                    count += 1

                    # Deep Scan for top project folders (index 2-4 key files inside the project)
                    if deep_scan and is_dir and not is_app and count <= 8:
                        try:
                            sub_files = [sf for sf in item.iterdir() if not sf.name.startswith(".") and not sf.is_dir()]
                            sub_files = sub_files[:4]  # index up to 4 key files
                            for sf_idx, sf in enumerate(sub_files):
                                sf_ext = sf.suffix.lower()
                                sf_cat, sf_type = EXT_CATEGORIES.get(sf_ext, ("Files", "File"))
                                category_counts[sf_cat] = category_counts.get(sf_cat, 0) + 1

                                sf_stat = sf.stat()
                                sf_size = _format_size(sf_stat.st_size)
                                sf_mtime = datetime.fromtimestamp(sf_stat.st_mtime).strftime("%b %d, %Y")

                                sub_node_id = f"sub_{node_id}_{sf_idx}"
                                sub_node = {
                                    "id": sub_node_id,
                                    "name": sf.name,
                                    "type": sf_type,
                                    "category": sf_cat,
                                    "path": str(sf),
                                    "hub": hub_name,
                                    "hub_id": hub_id,
                                    "parent_project": display_name,
                                    "parent_node_id": node_id,
                                    "is_app": False,
                                    "is_dir": False,
                                    "size_bytes": sf_stat.st_size,
                                    "size_human": sf_size,
                                    "mtime": sf_mtime,
                                    "summary": f"Key file ({sf_size}) inside {display_name} project. Path: {sf}.",
                                    "is_text_readable": sf_ext in [".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sh", ".env"],
                                }
                                nodes_out.append(sub_node)
                                # Edge from project node to child file
                                edges_out.append({
                                    "source": node_id,
                                    "target": sub_node_id,
                                    "category": sf_cat,
                                })
                        except Exception as sub_err:
                            logger.debug(f"Deep scan error on {item}: {sub_err}")

                    if count >= max_items:
                        break

            except Exception as e:
                logger.warning(f"Error scanning hub {hub_name} at {path}: {e}")

            hubs_out.append({
                "id": hub_id,
                "name": hub_name,
                "category": default_cat,
                "color": color,
                "count": len(child_nodes),
                "path": str(path),
                "pos": {"x": pos[0], "y": pos[1], "z": pos[2]},
            })

        # Virtual Hub: SQLite Semantic Memory Vault
        if memory_store is not None:
            memories = memory_store.list_recent(limit=40)
            mem_hub_id = "hub_memory_vault"
            mem_hub_name = "Memory Vault"
            for mem in memories:
                cat = "Brain"
                category_counts[cat] = category_counts.get(cat, 0) + 1
                nodes_out.append({
                    "id": mem["id"],
                    "name": mem["topic"],
                    "type": f"Memory ({mem['category']})",
                    "category": cat,
                    "path": f"memory://{mem['id']}",
                    "hub": mem_hub_name,
                    "hub_id": mem_hub_id,
                    "is_app": False,
                    "is_dir": False,
                    "size_human": f"Imp {mem['importance']}/5",
                    "mtime": mem["created_at"][:10],
                    "summary": mem["content"],
                    "is_text_readable": False,
                })
            hubs_out.append({
                "id": mem_hub_id,
                "name": mem_hub_name,
                "category": "Brain",
                "color": 0x22d3ee,
                "count": len(memories),
                "path": str(memory_store.db_path),
                "pos": {"x": -110, "y": 30, "z": 170},
            })

        # Virtual Hub: MCP Bridges
        if mcp_manager is not None:
            mcp_servers = mcp_manager.list_servers_status()
            mcp_hub_id = "hub_mcp_bridges"
            mcp_hub_name = "MCP Bridges"
            mcp_count = 0
            for srv in mcp_servers:
                for tname in srv.get("tools") or [srv["name"]]:
                    cat = "Config"
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    nodes_out.append({
                        "id": f"mcp_{srv['name']}_{tname}",
                        "name": tname,
                        "type": f"MCP ({srv['name']})",
                        "category": cat,
                        "path": f"mcp://{srv['name']}/{tname}",
                        "hub": mcp_hub_name,
                        "hub_id": mcp_hub_id,
                        "is_app": False,
                        "is_dir": False,
                        "size_human": "connected" if srv["connected"] else "disabled",
                        "mtime": "Live",
                        "summary": f"MCP Bridge tool '{tname}' exposed by server '{srv['name']}'.",
                        "is_text_readable": False,
                    })
                    mcp_count += 1
            hubs_out.append({
                "id": mcp_hub_id,
                "name": mcp_hub_name,
                "category": "Config",
                "color": 0xf59e0b,
                "count": mcp_count,
                "path": str(mcp_manager.config_path),
                "pos": {"x": 110, "y": -40, "z": -170},
            })

        return {
            "hubs": hubs_out,
            "nodes": nodes_out,
            "edges": edges_out,
            "categories": category_counts,
            "total_nodes": len(nodes_out),
            "total_hubs": len(hubs_out),
        }
