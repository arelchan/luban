"""Load audio files as base64 → ContentPart for models that support audio."""

from __future__ import annotations

import base64
from pathlib import Path

from agentkit.model.types import ContentPart

_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


def _guess_mime(path_or_url: str) -> str:
    lower = path_or_url.lower()
    for ext, mime in _MIME_MAP.items():
        if lower.endswith(ext):
            return mime
    return "audio/mpeg"


async def load_audio(path_or_url: str, is_url: bool = False) -> ContentPart:
    """Load an audio file and return a ContentPart.

    For URLs: keep source_url so the API can fetch directly.
    For local files: base64 encode.
    Models that support audio will process it; others will tell the user.
    """
    if is_url:
        return ContentPart(
            type="audio",
            media_type=_guess_mime(path_or_url),
            source_url=path_or_url,
        )

    file_path = Path(path_or_url).expanduser().resolve()
    if not file_path.exists():
        return ContentPart(type="text", text=f"[错误：文件不存在 {path_or_url}]")

    data = file_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    mime = _guess_mime(str(file_path))

    return ContentPart(type="audio", media_type=mime, data=encoded)
