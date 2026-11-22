"""
Perception modules for F.R.I.D.A.Y: EYES (screen vision) and FOCUS (active window awareness).
"""
from .screen import ScreenVisionEngine, compute_dhash, dhash_distance, compress_image_bytes
from .focus import FocusMonitor, FocusContext

__all__ = [
    "ScreenVisionEngine",
    "compute_dhash",
    "dhash_distance",
    "compress_image_bytes",
    "FocusMonitor",
    "FocusContext",
]
