"""Media processing module — detect and process images, videos, and audio."""

from agentkit.media.detector import MediaRef, detect_media
from agentkit.media.processor import process_media_refs

__all__ = ["MediaRef", "detect_media", "process_media_refs"]
