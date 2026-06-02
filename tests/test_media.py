"""Tests for agentkit.media — detection, image loading, video frames, audio."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest

from agentkit.media.detector import MediaRef, detect_media
from agentkit.model.types import ContentPart, Message


class TestDetectMedia:
    def test_no_media(self):
        text, refs = detect_media("Hello, how are you?")
        assert text == "Hello, how are you?"
        assert refs == []

    def test_detect_image_path(self):
        text, refs = detect_media("分析这张图 /tmp/screenshot.png")
        assert "screenshot.png" not in text
        assert len(refs) == 1
        assert refs[0].media_type == "image"
        assert refs[0].raw == "/tmp/screenshot.png"
        assert refs[0].is_url is False

    def test_detect_image_tilde_path(self):
        text, refs = detect_media("看看 ~/Desktop/photo.jpg")
        assert len(refs) == 1
        assert refs[0].media_type == "image"
        assert refs[0].raw == "~/Desktop/photo.jpg"

    def test_detect_video_path(self):
        text, refs = detect_media("这个视频 /tmp/demo.mp4 怎么样")
        assert len(refs) == 1
        assert refs[0].media_type == "video"

    def test_detect_audio_path(self):
        text, refs = detect_media("听听 /tmp/voice.mp3")
        assert len(refs) == 1
        assert refs[0].media_type == "audio"

    def test_detect_url_image(self):
        text, refs = detect_media("帮我看看 https://example.com/photo.png")
        assert len(refs) == 1
        assert refs[0].is_url is True
        assert refs[0].media_type == "image"

    def test_detect_url_video(self):
        text, refs = detect_media("分析 https://cdn.example.com/video.mp4")
        assert len(refs) == 1
        assert refs[0].media_type == "video"
        assert refs[0].is_url is True

    def test_multiple_refs(self):
        text, refs = detect_media("比较 /tmp/a.png 和 /tmp/b.jpg")
        assert len(refs) == 2
        assert all(r.media_type == "image" for r in refs)

    def test_clean_text_preserves_intent(self):
        text, refs = detect_media("请分析这张截图 /tmp/test.png 的内容")
        assert "请分析这张截图" in text
        assert "的内容" in text
        assert "/tmp/test.png" not in text

    def test_webp_extension(self):
        _, refs = detect_media("/tmp/image.webp")
        assert len(refs) == 1
        assert refs[0].media_type == "image"

    def test_mkv_extension(self):
        _, refs = detect_media("看 /tmp/movie.mkv")
        assert len(refs) == 1
        assert refs[0].media_type == "video"

    def test_flac_extension(self):
        _, refs = detect_media("/tmp/song.flac")
        assert len(refs) == 1
        assert refs[0].media_type == "audio"


class TestContentPart:
    def test_text_to_openai(self):
        p = ContentPart(type="text", text="hello")
        assert p.to_openai_dict() == {"type": "text", "text": "hello"}

    def test_text_to_anthropic(self):
        p = ContentPart(type="text", text="hello")
        assert p.to_anthropic_dict() == {"type": "text", "text": "hello"}

    def test_image_base64_to_openai(self):
        p = ContentPart(type="image", media_type="image/png", data="abc123")
        d = p.to_openai_dict()
        assert d["type"] == "image_url"
        assert "data:image/png;base64,abc123" in d["image_url"]["url"]

    def test_image_url_to_openai(self):
        p = ContentPart(type="image", source_url="https://example.com/img.png")
        d = p.to_openai_dict()
        assert d["image_url"]["url"] == "https://example.com/img.png"

    def test_image_base64_to_anthropic(self):
        p = ContentPart(type="image", media_type="image/jpeg", data="xyz")
        d = p.to_anthropic_dict()
        assert d["type"] == "image"
        assert d["source"]["type"] == "base64"
        assert d["source"]["data"] == "xyz"

    def test_image_url_to_anthropic(self):
        p = ContentPart(type="image", source_url="https://example.com/img.png")
        d = p.to_anthropic_dict()
        assert d["source"]["type"] == "url"


class TestMessageMultimodal:
    def test_text_content_property_str(self):
        m = Message(role="user", content="hello")
        assert m.text_content == "hello"

    def test_text_content_property_parts(self):
        m = Message(role="user", content=[
            ContentPart(type="text", text="describe this"),
            ContentPart(type="image", data="abc"),
        ])
        assert m.text_content == "describe this"

    def test_to_litellm_dict_str(self):
        m = Message(role="user", content="hello")
        d = m.to_litellm_dict()
        assert d["content"] == "hello"

    def test_to_litellm_dict_multimodal(self):
        m = Message(role="user", content=[
            ContentPart(type="text", text="what is this?"),
            ContentPart(type="image", media_type="image/png", data="base64data"),
        ])
        d = m.to_litellm_dict()
        assert isinstance(d["content"], list)
        assert len(d["content"]) == 2
        assert d["content"][0] == {"type": "text", "text": "what is this?"}
        assert d["content"][1]["type"] == "image_url"

    def test_to_litellm_dict_tool_always_str(self):
        m = Message(role="tool", content="result", tool_call_id="tc1", name="read_file")
        d = m.to_litellm_dict()
        assert isinstance(d["content"], str)


class TestImageLoader:
    @pytest.mark.asyncio
    async def test_load_local_image(self):
        from agentkit.media.image import load_image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            f.flush()
            part = await load_image(f.name)

        assert part.type == "image"
        assert part.media_type == "image/png"
        assert part.data is not None
        # Verify base64 is valid
        base64.b64decode(part.data)

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self):
        from agentkit.media.image import load_image
        part = await load_image("/tmp/nonexistent_xyz_123.png")
        assert part.type == "text"
        assert "不存在" in part.text

    @pytest.mark.asyncio
    async def test_load_url_image(self):
        from agentkit.media.image import load_image
        part = await load_image("https://example.com/photo.jpg", is_url=True)
        assert part.type == "image"
        assert part.source_url == "https://example.com/photo.jpg"


class TestImageResize:
    @pytest.mark.asyncio
    async def test_small_image_no_resize(self):
        """Images under the limit should not be resized."""
        from agentkit.media.image import load_image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            # Write a tiny valid-ish file (under any limit)
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            f.flush()
            part = await load_image(f.name, max_size_mb=20)

        assert part.type == "image"
        assert part.data is not None

    @pytest.mark.asyncio
    async def test_large_image_gets_resized(self):
        """Images over the limit should be resized with Pillow."""
        pytest.importorskip("PIL")
        from PIL import Image as PILImage
        from agentkit.media.image import load_image

        # Create a large image (2000x2000 RGB ≈ 12MB uncompressed)
        img = PILImage.new("RGB", (2000, 2000), color=(255, 0, 0))
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            img.save(f, format="BMP")
            f.flush()
            path = f.name

        # Set a very small limit to force resize
        part = await load_image(path, max_size_mb=1)

        assert part.type == "image"
        assert part.data is not None
        # Verify the resulting data is under 1MB
        raw_size = len(base64.b64decode(part.data))
        assert raw_size <= 1 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_resize_preserves_alpha(self):
        """RGBA images should stay PNG after resize."""
        pytest.importorskip("PIL")
        from PIL import Image as PILImage
        from agentkit.media.image import load_image

        img = PILImage.new("RGBA", (2000, 2000), color=(255, 0, 0, 128))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f, format="PNG")
            f.flush()
            path = f.name

        part = await load_image(path, max_size_mb=1)
        assert part.type == "image"
        assert part.media_type == "image/png"


class TestEstimateTokens:
    def test_multimodal_tokens(self):
        from agentkit.memory.short_term import estimate_tokens
        msgs = [Message(role="user", content=[
            ContentPart(type="text", text="describe"),
            ContentPart(type="image", data="x" * 1000),
        ])]
        tokens = estimate_tokens(msgs)
        # text: 8 chars / 2 = 4 tokens, image: 2000 chars / 2 = 1000 tokens
        assert tokens >= 1000
