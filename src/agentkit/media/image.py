"""Load images from local paths or URLs → ContentPart."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from agentkit.model.types import ContentPart

logger = logging.getLogger(__name__)

# Extension → MIME type
_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _guess_mime(path_or_url: str) -> str:
    """Guess MIME type from extension."""
    lower = path_or_url.lower()
    for ext, mime in _MIME_MAP.items():
        if lower.endswith(ext):
            return mime
    return "image/png"


def _resize_image_bytes(data: bytes, max_size_mb: int) -> tuple[bytes, str]:
    """Resize image if it exceeds max_size_mb. Returns (data, mime).

    Uses Pillow to scale down proportionally until under the limit.
    Output format is JPEG (for compression efficiency) unless the original is PNG with alpha.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed, skipping image resize. Install with: pip install Pillow")
        return data, _guess_mime("")  # fallback, can't resize

    img = Image.open(io.BytesIO(data))
    has_alpha = img.mode in ("RGBA", "LA", "PA")

    # Choose output format
    if has_alpha:
        out_format, mime = "PNG", "image/png"
    else:
        out_format, mime = "JPEG", "image/jpeg"
        if img.mode != "RGB":
            img = img.convert("RGB")

    max_bytes = max_size_mb * 1024 * 1024

    # If already under limit, return as-is
    if len(data) <= max_bytes:
        return data, mime

    # Iteratively scale down by 75% until under limit (max 5 iterations)
    for _ in range(5):
        new_w = int(img.width * 0.75)
        new_h = int(img.height * 0.75)
        if new_w < 100 or new_h < 100:
            break
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format=out_format, quality=85)
        out_data = buf.getvalue()
        if len(out_data) <= max_bytes:
            logger.info("Resized image: %dx%d, %.1f MB", new_w, new_h, len(out_data) / 1024 / 1024)
            return out_data, mime

    # Final attempt — return whatever we got
    buf = io.BytesIO()
    img.save(buf, format=out_format, quality=75)
    return buf.getvalue(), mime


async def load_image(
    path_or_url: str,
    is_url: bool = False,
    max_size_mb: int = 20,
) -> ContentPart:
    """Load an image and return a ContentPart.

    For URLs: keep source_url so the API can fetch directly (saves bandwidth).
    For local files: base64 encode, auto-resize if exceeds max_size_mb.
    """
    if is_url:
        # Let the model API fetch the URL directly
        return ContentPart(
            type="image",
            media_type=_guess_mime(path_or_url),
            source_url=path_or_url,
        )

    # Local file
    file_path = Path(path_or_url).expanduser().resolve()
    if not file_path.exists():
        return ContentPart(type="text", text=f"[错误：文件不存在 {path_or_url}]")

    data = file_path.read_bytes()
    mime = _guess_mime(str(file_path))

    # Auto-resize if exceeds limit
    if len(data) > max_size_mb * 1024 * 1024:
        data, mime = _resize_image_bytes(data, max_size_mb)

    encoded = base64.b64encode(data).decode("ascii")
    return ContentPart(type="image", media_type=mime, data=encoded)
