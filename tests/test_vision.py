"""Tests for Phase 2 Vision & Perception: EYES (screen + dhash) and FOCUS (active window)."""
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from PIL import Image

from src.vision.screen import ScreenVisionEngine, compute_dhash, dhash_distance, compress_image_bytes
from src.vision.focus import FocusMonitor, FocusContext
from src.tools.workspace import build_default_registry


def _make_png_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    # Draw distinct stripe so different colors/patterns produce distinct dhashes
    for x in range(width // 2):
        for y in range(height // 2):
            img.putpixel((x, y), (255 - color[0], color[1], color[2]))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_compress_image_downscales_and_returns_jpeg():
    raw_png = _make_png_bytes(2560, 1440, (20, 80, 160))
    jpeg_bytes, width, height = compress_image_bytes(raw_png, max_width=1280, quality=75)
    assert width == 1280
    assert height == 720
    with Image.open(BytesIO(jpeg_bytes)) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.size == (1280, 720)


def test_dhash_deduplication_and_ring_buffer():
    png_a = _make_png_bytes(800, 600, (10, 20, 200))
    png_b = _make_png_bytes(800, 600, (240, 20, 10))
    # Inverted split stripe for genuinely different hash
    img_c = Image.new("RGB", (800, 600), color=(30, 220, 40))
    for x in range(400, 800):
        for y in range(300, 600):
            img_c.putpixel((x, y), (250, 10, 200))
    buf_c = BytesIO()
    img_c.save(buf_c, format="PNG")
    png_c = buf_c.getvalue()

    h_a = compute_dhash(png_a)
    h_c = compute_dhash(png_c)
    assert dhash_distance(h_a, h_a) == 0
    assert dhash_distance(h_a, h_c) > 3

    engine = ScreenVisionEngine(max_frames=3)
    att1, changed1 = engine.ingest_raw_bytes(png_a, label="screen_1")
    att2, changed2 = engine.ingest_raw_bytes(png_a, label="screen_dup")
    att3, changed3 = engine.ingest_raw_bytes(png_c, label="screen_2")

    assert changed1 is True
    assert changed2 is False
    assert changed3 is True
    # Only 2 unique frames stored even after duplicate
    assert len(engine.recent_frames) == 2
    assert engine.latest_attachment().label == "screen_2"


@pytest.mark.anyio
async def test_screen_capture_handles_failure_gracefully():
    engine = ScreenVisionEngine(max_frames=3)
    with patch.object(engine, "_capture_raw_screencapture", side_effect=RuntimeError("Permission denied")):
        res = await engine.capture_now()
        assert res is None
        assert engine.last_error == "Permission denied"


def test_focus_monitor_parses_active_window_and_gates_notifications():
    mon = FocusMonitor()
    ctx = mon.parse_osascript_output("Code|||main.py — F.R.I.D.A.Y")
    assert ctx.app_name == "Code"
    assert ctx.window_title == "main.py — F.R.I.D.A.Y"

    mon.set_focus_mode(True)
    mon._cached_context = ctx
    assert mon.should_suppress_notification(priority="normal") is True
    assert mon.should_suppress_notification(priority="critical") is False
    assert "Code" in mon.format_prompt_context()


def test_workspace_registry_registers_vision_tools(tmp_path: Path):
    screen = ScreenVisionEngine()
    focus = FocusMonitor()
    reg = build_default_registry(tmp_path, screen_engine=screen, focus_monitor=focus)
    assert reg.get("capture_screen") is not None
    assert reg.get("get_active_window") is not None
