"""Load video files as base64 → ContentPart for models that support video."""

from __future__ import annotations

import base64
from pathlib import Path

from agentkit.model.types import ContentPart

_MIME_MAP = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def _guess_mime(path_or_url: str) -> str:
    lower = path_or_url.lower()
    for ext, mime in _MIME_MAP.items():
        if lower.endswith(ext):
            return mime
    return "video/mp4"


async def load_video(path_or_url: str, is_url: bool = False) -> ContentPart:
    """Load a video and return a ContentPart.

    For URLs: keep source_url so the API can fetch directly.
    For local files: base64 encode.
    Models that support video will process it; others will tell the user.
    """
    if is_url:
        return ContentPart(
            type="video",
            media_type=_guess_mime(path_or_url),
            source_url=path_or_url,
        )

    file_path = Path(path_or_url).expanduser().resolve()
    if not file_path.exists():
        return ContentPart(type="text", text=f"[错误：文件不存在 {path_or_url}]")

    data = file_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    mime = _guess_mime(str(file_path))

    return ContentPart(type="video", media_type=mime, data=encoded)
