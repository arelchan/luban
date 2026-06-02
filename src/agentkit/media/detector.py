"""Detect media references (file paths and URLs) in user input."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Supported extensions by media type
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
ALL_MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS

# Pattern for local file paths (absolute, ~/, or ./)
_PATH_PATTERN = re.compile(
    r"""(?:^|\s)("""
    r"""(?:[/~][\w./\-~]+|\.[\w./\-]+)"""  # /path, ~/path, ./path
    r"""\.(?:""" + "|".join(ext.lstrip(".") for ext in sorted(ALL_MEDIA_EXTS)) + r""")"""
    r""")(?:\s|$)""",
    re.IGNORECASE,
)

# Pattern for URLs ending in media extensions
_URL_PATTERN = re.compile(
    r"""(https?://\S+\.(?:""" + "|".join(ext.lstrip(".") for ext in sorted(ALL_MEDIA_EXTS)) + r"""))""",
    re.IGNORECASE,
)


@dataclass
class MediaRef:
    """A detected media reference in user input."""

    raw: str                                         # Original matched string
    media_type: Literal["image", "video", "audio"]   # Category
    is_url: bool = False                             # True if HTTP(S) URL


def _classify_ext(path: str) -> Literal["image", "video", "audio"] | None:
    """Classify a path/URL by its extension."""
    lower = path.lower()
    for ext in IMAGE_EXTS:
        if lower.endswith(ext):
            return "image"
    for ext in VIDEO_EXTS:
        if lower.endswith(ext):
            return "video"
    for ext in AUDIO_EXTS:
        if lower.endswith(ext):
            return "audio"
    return None


def detect_media(text: str) -> tuple[str, list[MediaRef]]:
    """Detect media references in user input text.

    Returns:
        (clean_text, media_refs) — text with media references removed, and list of refs.
    """
    refs: list[MediaRef] = []
    found_spans: list[tuple[int, int, str, bool]] = []  # (start, end, matched, is_url)

    # Find URLs first (higher priority — don't let path pattern eat them)
    for m in _URL_PATTERN.finditer(text):
        url = m.group(1)
        cat = _classify_ext(url)
        if cat:
            refs.append(MediaRef(raw=url, media_type=cat, is_url=True))
            found_spans.append((m.start(1), m.end(1), url, True))

    # Find local paths (skip if overlapping with URL matches)
    for m in _PATH_PATTERN.finditer(text):
        path = m.group(1)
        start, end = m.start(1), m.end(1)
        # Skip if overlapping with a URL match
        if any(s <= start < e or s < end <= e for s, e, _, _ in found_spans):
            continue
        cat = _classify_ext(path)
        if cat:
            refs.append(MediaRef(raw=path, media_type=cat, is_url=False))
            found_spans.append((start, end, path, False))

    if not refs:
        return text, []

    # Remove matched refs from text
    clean = text
    for raw_str in sorted((r.raw for r in refs), key=len, reverse=True):
        clean = clean.replace(raw_str, "").strip()
    # Collapse multiple spaces
    clean = re.sub(r"\s{2,}", " ", clean).strip()

    return clean, refs
