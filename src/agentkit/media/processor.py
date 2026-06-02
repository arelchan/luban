"""Process detected media references into ContentParts."""

from __future__ import annotations

from agentkit.media.audio import load_audio
from agentkit.media.detector import MediaRef
from agentkit.media.image import load_image
from agentkit.media.video import load_video
from agentkit.model.types import ContentPart


async def process_media_refs(
    refs: list[MediaRef],
    clean_text: str,
) -> list[ContentPart]:
    """Process media references and build a multimodal content list.

    Args:
        refs: Detected media references from detect_media().
        clean_text: User text with media refs removed.

    Returns:
        List of ContentPart (text + images/video/audio).
    """
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts: list[ContentPart] = []

    # Add text part first (with timestamp)
    if clean_text:
        parts.append(ContentPart(type="text", text=f"[{ts}] {clean_text}"))

    # Process each media ref
    for ref in refs:
        if ref.media_type == "image":
            part = await load_image(ref.raw, is_url=ref.is_url)
            parts.append(part)

        elif ref.media_type == "video":
            part = await load_video(ref.raw, is_url=ref.is_url)
            parts.append(part)

        elif ref.media_type == "audio":
            part = await load_audio(ref.raw, is_url=ref.is_url)
            parts.append(part)

    return parts
