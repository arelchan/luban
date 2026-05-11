"""Embedding client for long-term memory vectorization.

Supports OpenAI-compatible endpoints (OpenAI, custom proxy, Ollama, etc.).
Gracefully degrades when embedding is not configured — callers receive None
and should skip vector operations.
"""

from __future__ import annotations

from typing import Any

import httpx

from agentkit.config.models import EmbeddingConfig


class Embedder:
    """Compute text embeddings via an OpenAI-compatible /embeddings endpoint.

    If embedding is disabled or misconfigured, all methods return None without
    raising — callers must handle None and fall back to text-only operation.
    """

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled and bool(
            self._config.api_key or self._config.base_url
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _base_url(self) -> str:
        if self._config.base_url:
            return self._config.base_url.rstrip("/")
        # Default OpenAI endpoint
        return "https://api.openai.com/v1"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    async def embed(self, text: str) -> list[float] | None:
        """Embed a single text. Returns None if embedding is disabled or fails."""
        result = await self.embed_batch([text])
        if result and result[0] is not None:
            return result[0]
        return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed multiple texts in one API call. Returns list aligned with input."""
        if not self.enabled or not texts:
            return [None] * len(texts)

        # Filter empty texts
        non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
        if not non_empty:
            return [None] * len(texts)

        results: list[list[float] | None] = [None] * len(texts)
        try:
            payload: dict[str, Any] = {
                "input": [t for _, t in non_empty],
                "model": self._config.model,
            }
            if self._config.dimensions:
                payload["dimensions"] = self._config.dimensions

            client = self._get_client()
            resp = await client.post(
                f"{self._base_url()}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            embeddings = data.get("data", [])
            for batch_idx, (orig_idx, _) in enumerate(non_empty):
                if batch_idx < len(embeddings):
                    results[orig_idx] = embeddings[batch_idx].get("embedding")

        except Exception:
            # Silently degrade — callers handle None
            pass

        return results

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
