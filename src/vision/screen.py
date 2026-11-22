"""
EYES: On-demand & change-gated macOS screen vision engine for F.R.I.D.A.Y.
Downscales screen captures with Pillow and deduplicates unchanged frames via 64-bit dhash.
"""
import asyncio
import base64
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.llm.base import ImageAttachment

logger = logging.getLogger("FRIDAY.Vision.Screen")


def compute_dhash(image_bytes: bytes, hash_size: int = 8) -> int:
    """Compute a 64-bit difference hash (dhash) over a grayscale resized thumbnail."""
    with Image.open(BytesIO(image_bytes)) as img:
        gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.BILINEAR)
        pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())

    diff = 0
    bit_idx = 0
    row_width = hash_size + 1
    for y in range(hash_size):
        row_start = y * row_width
        for x in range(hash_size):
            if pixels[row_start + x] > pixels[row_start + x + 1]:
                diff |= 1 << bit_idx
            bit_idx += 1
    return diff


def dhash_distance(hash_a: int, hash_b: int) -> int:
    """Hamming distance between two integer dhashes."""
    return (hash_a ^ hash_b).bit_count()


def compress_image_bytes(
    raw_bytes: bytes,
    max_width: int = 1280,
    quality: int = 75,
) -> tuple[bytes, int, int]:
    """Resize down to max_width preserving aspect ratio and encode as baseline JPEG."""
    with Image.open(BytesIO(raw_bytes)) as img:
        rgb = img.convert("RGB")
        w, h = rgb.size
        if max_width > 0 and w > max_width:
            new_h = max(1, int(round(h * (max_width / w))))
            rgb = rgb.resize((max_width, new_h), Image.Resampling.LANCZOS)
        out_w, out_h = rgb.size
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), out_w, out_h


@dataclass
class BufferedFrame:
    attachment: ImageAttachment
    dhash: int
    width: int
    height: int
    captured_at: float


class ScreenVisionEngine:
    """Manages macOS screen captures, JPEG compression, and a 3-frame rolling buffer."""

    def __init__(self, max_frames: int = 3, dedup_threshold: int = 3):
        self.max_frames = max(1, max_frames)
        self.dedup_threshold = dedup_threshold
        self.enabled: bool = False
        self.recent_frames: deque[BufferedFrame] = deque(maxlen=self.max_frames)
        self.last_error: str | None = None

    def latest_attachment(self) -> ImageAttachment | None:
        if not self.recent_frames:
            return None
        return self.recent_frames[-1].attachment

    def ingest_raw_bytes(
        self,
        raw_bytes: bytes,
        label: str = "screen",
        max_width: int = 1280,
        quality: int = 75,
    ) -> tuple[ImageAttachment, bool]:
        """Compress raw image bytes, check dhash change, and update ring buffer."""
        jpeg_bytes, width, height = compress_image_bytes(raw_bytes, max_width=max_width, quality=quality)
        new_hash = compute_dhash(jpeg_bytes)

        changed = True
        if self.recent_frames:
            prev = self.recent_frames[-1]
            if dhash_distance(prev.dhash, new_hash) <= self.dedup_threshold:
                changed = False

        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        attachment = ImageAttachment(base64_data=b64, mime_type="image/jpeg", label=label)

        if changed or not self.recent_frames:
            self.recent_frames.append(
                BufferedFrame(
                    attachment=attachment,
                    dhash=new_hash,
                    width=width,
                    height=height,
                    captured_at=time.time(),
                )
            )
            return attachment, True

        return self.recent_frames[-1].attachment, False

    async def _capture_raw_screencapture(self) -> bytes:
        fd, tmp_path = tempfile.mkstemp(prefix="friday_eyes_", suffix=".png")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/sbin/screencapture",
                "-x",
                "-t",
                "png",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=6.0)
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace").strip() or f"screencapture exit {proc.returncode}"
                raise RuntimeError(err)
            return Path(tmp_path).read_bytes()
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def capture_now(self, label: str = "screen") -> ImageAttachment | None:
        """Capture main display right now; returns compressed ImageAttachment or None on error."""
        try:
            raw = await self._capture_raw_screencapture()
            attachment, _ = self.ingest_raw_bytes(raw, label=label)
            self.last_error = None
            return attachment
        except Exception as e:
            self.last_error = str(e)
            logger.warning(f"Screen capture failed: {e}")
            return None
