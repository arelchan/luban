"""Model client with support for direct API calls and LiteLLM fallback."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agentkit.config.models import ModelConfig, ProviderConfig
from agentkit.model.types import (
    Message,
    ModelResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


def _get_litellm():
    """Lazily import litellm on first use to avoid slowing down startup."""
    import litellm as _litellm
    _litellm.suppress_debug_info = True
    return _litellm


class ContextWindowExceeded(Exception):
    """Raised when the input exceeds the model's context window limit."""

    pass


class ModelClient:
    """Unified LLM client.

    Two modes:
    - base_url configured: Direct httpx calls (full control over URL and headers)
    - no base_url: Delegate to LiteLLM (official endpoints)

    This ensures proxies/custom endpoints always work predictably.
    """

    def __init__(self, config: ModelConfig):
        self._config = config
        self._http_client: httpx.AsyncClient | None = None
        # Track cumulative token usage for context display
        self.last_usage: TokenUsage | None = None
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cache_creation_tokens: int = 0
        self.total_cache_read_tokens: int = 0

    def _resolve_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Find the provider that serves the given model."""
        target = model or self._config.default
        for p in self._config.providers:
            if target in p.models:
                return p
        return None

    def _get_api_key(self) -> str | None:
        """Get the first available API key from config (legacy)."""
        if self._config.api_keys:
            return next(iter(self._config.api_keys.values()))
        return None

    def _get_model_name(self, model: str | None = None) -> str:
        """Get the raw model name (without provider prefix like 'anthropic/')."""
        full = model or self._config.default
        # Strip provider prefix: "anthropic/aws.claude-sonnet-4.6" → "aws.claude-sonnet-4.6"
        if "/" in full:
            return full.split("/", 1)[1]
        return full

    def _get_provider(self, model: str | None = None) -> str:
        """Get the provider from model name (legacy)."""
        full = model or self._config.default
        if "/" in full:
            return full.split("/", 1)[0]
        return "anthropic"

    def _has_providers(self) -> bool:
        """Check if new-style providers are configured."""
        return bool(self._config.providers)

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    # ─── Public API ───

    def _should_use_direct(self, model: str | None = None) -> bool:
        """Determine if we should use direct HTTP calls."""
        if self._has_providers():
            return self._resolve_provider(model) is not None
        return bool(self._config.base_url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> ModelResponse:
        """Non-streaming completion."""
        if self._should_use_direct(model):
            return await self._direct_complete(messages, tools, model)
        return await self._litellm_complete(messages, tools, model)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion."""
        if self._should_use_direct(model):
            async for chunk in self._direct_stream(messages, tools, model):
                yield chunk
        else:
            async for chunk in self._litellm_stream(messages, tools, model):
                yield chunk

    async def shutdown(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    # ─── Direct HTTP calls (for custom base_url) ───

    def _build_direct_request(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        stream: bool = False,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Build URL, headers, and body for direct API call.

        Supports both new-style providers and legacy single base_url.
        """
        # Resolve provider info (new-style or legacy)
        resolved = self._resolve_provider(model)
        if resolved:
            base = resolved.base_url.rstrip("/")
            api_format = resolved.format
            api_key = resolved.api_key
            model_name = model or self._config.default
        else:
            # Legacy fallback
            base = self._config.base_url.rstrip("/")
            api_format = "anthropic" if self._get_provider(model) == "anthropic" else "openai"
            model_name = self._get_model_name(model)
            api_key = self._get_api_key()

        if api_format == "anthropic":
            url = f"{base}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}" if api_key else "",
                "anthropic-version": "2023-06-01",
            }
            # Convert messages to Anthropic format
            system_text = ""
            api_messages = []
            for m in messages:
                if m.role == "system":
                    system_text += (m.content or "") + "\n"
                elif m.role == "tool":
                    api_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id,
                            "content": m.content or "",
                        }],
                    })
                elif m.role == "assistant" and m.tool_calls:
                    content_blocks = []
                    if m.content:
                        content_blocks.append({"type": "text", "text": m.content})
                    for tc in m.tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                    api_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    api_messages.append({"role": m.role, "content": m.content or ""})

            body: dict[str, Any] = {
                "model": model_name,
                "messages": api_messages,
                "max_tokens": self._config.options.max_tokens,
            }
            # Extended thinking mode
            if self._config.options.thinking:
                body["temperature"] = 1  # Required for thinking mode
                body["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self._config.options.thinking_budget,
                }
            else:
                body["temperature"] = self._config.options.temperature
            if system_text.strip():
                body["system"] = system_text.strip()
            if stream:
                body["stream"] = True
            if tools:
                # Convert OpenAI tool format to Anthropic format
                anthropic_tools = []
                for t in tools:
                    func = t["function"]
                    anthropic_tools.append({
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {}),
                    })
                body["tools"] = anthropic_tools

        else:
            # OpenAI-compatible format
            # New-style providers: base_url includes full prefix, append /chat/completions
            # Legacy: base_url is root, append /v1/chat/completions
            url = f"{base}/chat/completions" if resolved else f"{base}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}" if api_key else "",
            }
            litellm_messages = [m.to_litellm_dict() for m in messages]
            body: dict[str, Any] = {
                "model": model_name,
                "messages": litellm_messages,
                "max_tokens": self._config.options.max_tokens,
            }
            # Extended thinking mode for OpenAI-compatible format
            if self._config.options.thinking:
                body["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self._config.options.thinking_budget,
                }
            else:
                body["temperature"] = self._config.options.temperature
            if stream:
                body["stream"] = True
            if tools:
                body["tools"] = tools

        return url, headers, body

    def _get_api_format(self, model: str | None = None) -> str:
        """Get API format for the given model (new-style or legacy)."""
        resolved = self._resolve_provider(model)
        if resolved:
            return resolved.format
        return "anthropic" if self._get_provider(model) == "anthropic" else "openai"

    async def _direct_complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
    ) -> ModelResponse:
        """Direct HTTP non-streaming call."""
        url, headers, body = self._build_direct_request(messages, tools, model)
        client = await self._get_http_client()
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code == 400:
            self._check_context_window_error(resp)
        resp.raise_for_status()
        data = resp.json()

        api_format = self._get_api_format(model)
        if api_format == "anthropic":
            response = self._parse_anthropic_response(data)
        else:
            response = self._parse_openai_response(data)

        # Track usage
        if response.usage:
            self.last_usage = response.usage
            self.total_input_tokens += response.usage.prompt_tokens
            self.total_output_tokens += response.usage.completion_tokens
            self.total_cache_creation_tokens += response.usage.cache_creation_tokens
            self.total_cache_read_tokens += response.usage.cache_read_tokens
        return response

    async def _direct_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
    ) -> AsyncIterator[StreamChunk]:
        """Direct HTTP streaming call."""
        url, headers, body = self._build_direct_request(messages, tools, model, stream=True)
        client = await self._get_http_client()

        provider = self._get_api_format(model)

        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code == 400:
                # Need to read body for error detection in streaming mode
                body_bytes = b""
                async for chunk in resp.aiter_bytes():
                    body_bytes += chunk
                self._check_context_window_error_raw(body_bytes)
                # If not a context error, raise normally
                raise httpx.HTTPStatusError(
                    f"Client error '{resp.status_code}'",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()

            accumulated_tool_calls: dict[int, dict[str, Any]] = {}
            idx_counter = 0

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                elif line.startswith("data:"):
                    data_str = line[5:]
                else:
                    continue
                if data_str.strip() == "[DONE]":
                    break

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if provider == "anthropic":
                    chunk = self._parse_anthropic_stream_event(
                        event, accumulated_tool_calls, idx_counter
                    )
                    if chunk:
                        if chunk.tool_calls_delta:
                            idx_counter = len(accumulated_tool_calls)
                        yield chunk
                else:
                    chunk = self._parse_openai_stream_event(event, accumulated_tool_calls)
                    if chunk:
                        yield chunk

            # Emit final chunk with accumulated tool calls if any
            if accumulated_tool_calls:
                final_tools = []
                for _, tc_data in sorted(accumulated_tool_calls.items()):
                    try:
                        args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    final_tools.append(ToolCall(id=tc_data["id"], name=tc_data["name"], arguments=args))
                yield StreamChunk(is_final=True, tool_calls_delta=final_tools)
            else:
                yield StreamChunk(is_final=True)

    # ─── Anthropic response parsing ───

    def _parse_anthropic_response(self, data: dict) -> ModelResponse:
        """Parse Anthropic Messages API response."""
        content = ""
        tool_calls = []

        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))

        usage = None
        if "usage" in data:
            u = data["usage"]
            usage = TokenUsage(
                prompt_tokens=u.get("input_tokens", 0),
                completion_tokens=u.get("output_tokens", 0),
                total_tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0),
                cache_creation_tokens=u.get("cache_creation_input_tokens", 0) or 0,
                cache_read_tokens=u.get("cache_read_input_tokens", 0) or 0,
            )

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=data.get("stop_reason"),
        )

    def _parse_anthropic_stream_event(
        self, event: dict, accumulated_tools: dict, idx_counter: int
    ) -> StreamChunk | None:
        """Parse a single Anthropic SSE event."""
        event_type = event.get("type", "")

        if event_type == "message_start":
            # Capture input token usage (including cache)
            message = event.get("message", {})
            usage = message.get("usage", {})
            in_tokens = usage.get("input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0
            if in_tokens or cache_creation or cache_read:
                self.last_usage = TokenUsage(
                    prompt_tokens=in_tokens,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                )
                self.total_input_tokens += in_tokens
                self.total_cache_creation_tokens += cache_creation
                self.total_cache_read_tokens += cache_read
            return None

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                idx = event.get("index", idx_counter)
                accumulated_tools[idx] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": "",
                }
            return None

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                return StreamChunk(content_delta=delta.get("text", ""))
            elif delta.get("type") == "input_json_delta":
                # Accumulate tool input
                idx = event.get("index", 0)
                if idx in accumulated_tools:
                    accumulated_tools[idx]["arguments"] += delta.get("partial_json", "")
                return None

        elif event_type == "message_stop":
            return None  # Final chunk handled by caller

        elif event_type == "message_delta":
            # Contains stop_reason, usage (output tokens arrive here)
            usage = event.get("usage", {})
            if usage:
                out_tokens = usage.get("output_tokens", 0)
                in_tokens = usage.get("input_tokens", 0)
                if out_tokens:
                    self.total_output_tokens += out_tokens
                    if self.last_usage:
                        self.last_usage.completion_tokens = out_tokens
                        self.last_usage.total_tokens = self.last_usage.prompt_tokens + out_tokens
                if in_tokens:
                    self.total_input_tokens += in_tokens
            return None

        return None

    # ─── OpenAI response parsing ───

    def _parse_openai_response(self, data: dict) -> ModelResponse:
        """Parse OpenAI Chat Completions response."""
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content", "") or ""
        tool_calls = []
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc["id"], name=tc["function"]["name"], arguments=args
                ))
        usage = None
        if "usage" in data:
            u = data["usage"]
            usage = TokenUsage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )
        return ModelResponse(content=content, tool_calls=tool_calls, usage=usage)

    def _parse_openai_stream_event(
        self,
        event: dict,
        accumulated_tools: dict[int, dict[str, Any]] | None = None,
    ) -> StreamChunk | None:
        """Parse a single OpenAI SSE chunk."""
        # Detect inline error responses (proxy may wrap errors in SSE)
        if "error" in event and "choices" not in event:
            err_msg = event["error"].get("message", str(event["error"]))
            raise httpx.HTTPStatusError(
                f"API error in stream: {err_msg}",
                request=httpx.Request("POST", ""),
                response=httpx.Response(400),
            )

        choices = event.get("choices", [])
        if not choices:
            return None
        delta = choices[0].get("delta", {})
        content = delta.get("content", "")
        finish = choices[0].get("finish_reason")

        # Accumulate tool calls
        if accumulated_tools is not None and delta.get("tool_calls"):
            for tc_delta in delta["tool_calls"]:
                idx = tc_delta.get("index", 0)
                if idx not in accumulated_tools:
                    accumulated_tools[idx] = {"id": "", "name": "", "arguments": ""}
                if tc_delta.get("id"):
                    accumulated_tools[idx]["id"] = tc_delta["id"]
                func = tc_delta.get("function", {})
                if func.get("name"):
                    accumulated_tools[idx]["name"] = func["name"]
                if func.get("arguments"):
                    accumulated_tools[idx]["arguments"] += func["arguments"]

        if content:
            return StreamChunk(content_delta=content, is_final=finish is not None)
        if finish:
            return StreamChunk(is_final=True)
        return None

    # ─── LiteLLM fallback (no base_url) ───

    async def _litellm_complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
    ) -> ModelResponse:
        """Use LiteLLM for official endpoints (no custom base_url)."""
        model_name = model or self._config.default
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [m.to_litellm_dict() for m in messages],
            "temperature": self._config.options.temperature,
            "max_tokens": self._config.options.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        # Set API key in env for LiteLLM
        import os
        for provider, key in self._config.api_keys.items():
            env_var = f"{provider.upper()}_API_KEY"
            if key and not os.environ.get(env_var):
                os.environ[env_var] = key

        litellm = _get_litellm()
        try:
            response = await litellm.acompletion(**kwargs)
        except litellm.ContextWindowExceededError as e:
            raise ContextWindowExceeded(str(e)) from e
        choice = response.choices[0]
        msg = choice.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
                cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            )
            self.total_cache_creation_tokens += usage.cache_creation_tokens
            self.total_cache_read_tokens += usage.cache_read_tokens
        return ModelResponse(content=msg.content or "", tool_calls=tool_calls, usage=usage, stop_reason=choice.finish_reason)

    async def _litellm_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        model: str | None,
    ) -> AsyncIterator[StreamChunk]:
        """Use LiteLLM streaming for official endpoints."""
        model_name = model or self._config.default
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [m.to_litellm_dict() for m in messages],
            "temperature": self._config.options.temperature,
            "max_tokens": self._config.options.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        import os
        for provider, key in self._config.api_keys.items():
            env_var = f"{provider.upper()}_API_KEY"
            if key and not os.environ.get(env_var):
                os.environ[env_var] = key

        litellm = _get_litellm()
        try:
            response = await litellm.acompletion(**kwargs)
        except litellm.ContextWindowExceededError as e:
            raise ContextWindowExceeded(str(e)) from e
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}

        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            content_delta = delta.content or ""
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.id:
                        accumulated_tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            accumulated_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
            if finish_reason:
                final_tools = []
                for _, tc_data in sorted(accumulated_tool_calls.items()):
                    try:
                        args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    final_tools.append(ToolCall(id=tc_data["id"], name=tc_data["name"], arguments=args))
                yield StreamChunk(content_delta=content_delta, is_final=True, tool_calls_delta=final_tools or None)
            else:
                if content_delta:
                    yield StreamChunk(content_delta=content_delta)

    # ─── Context window error detection ───

    def _check_context_window_error(self, resp: httpx.Response) -> None:
        """Check if an HTTP 400 response is a context window exceeded error."""
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            return
        self._check_context_window_error_data(data)

    def _check_context_window_error_raw(self, body: bytes) -> None:
        """Check if raw response bytes indicate a context window error."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return
        self._check_context_window_error_data(data)

    def _check_context_window_error_data(self, data: dict) -> None:
        """Detect context window error from parsed response data."""
        # Anthropic: {"type": "error", "error": {"type": "invalid_request_error", "message": "... too long ..."}}
        error = data.get("error", {})
        if isinstance(error, dict):
            msg = error.get("message", "").lower()
        else:
            msg = str(error).lower()

        context_keywords = ("too long", "token limit", "context length", "maximum context", "exceeds")
        if any(kw in msg for kw in context_keywords):
            raise ContextWindowExceeded(msg)
