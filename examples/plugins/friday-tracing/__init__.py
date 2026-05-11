"""friday-tracing — 将 Luban trace 数据上报到 Friday 平台。

安装方式：
    mkdir -p ~/.agentkit/workspace/plugins
    cp -r examples/plugins/friday-tracing ~/.agentkit/workspace/plugins/
    # 编辑 ~/.agentkit/workspace/plugins/friday-tracing/plugin.toml，填写 agent_id

卸载方式：
    rm -rf ~/.agentkit/workspace/plugins/friday-tracing/
    重启 Luban 即生效。

Friday Trace 查看：
    https://friday.sankuai.com/app/observation/traceManagement
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from typing import Any

import httpx

from agentkit.plugins.manager import PluginContext, PluginHooks

logger = logging.getLogger("friday-tracing")

_TOKEN_URL = "https://ssosv.sankuai.com/sson/auth/oidc/v1/token"
_FRIDAY_AUDIENCE = "341cad4c9a"  # Friday 线上 clientId

_KIND_MAP = {
    "turn": "AGENT",
    "llm": "LLM",
    "tool": "TOOL",
    "subagent": "AGENT",
    "compression": "AGENT",
}


def _to_ms(ts: float | None) -> int:
    return int((ts or 0) * 1000)


def _to_uuid(hex_id: str) -> str:
    """Convert a hex span_id to UUID format required by Friday.

    Luban uses 16-char hex (e.g. "c069b09f79b54b3f").
    Friday requires standard UUID (e.g. "c069b09f-79b5-4b3f-xxxx-xxxxxxxxxxxx").
    We pad to 32 hex chars and format as UUID.
    """
    try:
        padded = hex_id.replace("-", "").ljust(32, "0")[:32]
        return str(uuid.UUID(padded))
    except Exception:
        return str(uuid.uuid4())


def _to_numeric_trace_id(hex_id: str) -> str:
    """Convert Luban's hex trace_id to Friday's required numeric format.

    Friday expects a 16-digit numeric string starting with '8'.
    We derive it deterministically from the hex ID.
    """
    # Take first 15 hex chars, convert to int, take last 15 digits, prefix with '8'
    try:
        numeric = int(hex_id[:15], 16) % (10 ** 15)
        return f"8{numeric:015d}"
    except Exception:
        return f"8{random.randint(0, 10**15 - 1):015d}"


def _safe_json(obj: Any) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


class _FridayClient:
    def __init__(self, base_url: str, agent_id: str, client_id: str, client_secret: str,
                 timeout_ms: int, log_errors: bool):
        self._base = base_url.rstrip("/")
        self._agent_id = agent_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_ms / 1000
        self._log_errors = log_errors
        self._token: str = ""
        self._token_expires: float = 0.0
        self._token_lock = threading.Lock()

    def _make_client_jwt(self) -> str:
        """Generate client_secret_jwt for SSO authentication."""
        import base64 as _b64
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self._client_id, "sub": self._client_id,
            "aud": _TOKEN_URL, "jti": str(now), "iat": now, "exp": now + 300,
        }
        def b64url(d):
            return _b64.urlsafe_b64encode(json.dumps(d, separators=(',', ':')).encode()).rstrip(b'=').decode()
        h, p = b64url(header), b64url(payload)
        import hmac as _hmac, hashlib as _hashlib
        sig = _b64.urlsafe_b64encode(
            _hmac.new(self._client_secret.encode(), f"{h}.{p}".encode(), _hashlib.sha256).digest()
        ).rstrip(b'=').decode()
        return f"{h}.{p}.{sig}"

    def _get_token(self) -> str:
        """Get Friday access token via two-step: client_credentials → token exchange."""
        with self._token_lock:
            if self._token and time.time() < self._token_expires:
                return self._token
            try:
                client_jwt = self._make_client_jwt()
                # Step 1: get self token
                resp1 = httpx.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "client_assertion": client_jwt,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                resp1.raise_for_status()
                self_token = resp1.json().get("access_token", "")
                if not self_token:
                    raise ValueError(f"No access_token in step1 response: {resp1.text[:200]}")

                # Step 2: exchange for Friday-audience token
                resp2 = httpx.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                        "client_id": self._client_id,
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "client_assertion": self._make_client_jwt(),
                        "subject_token": self_token,
                        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                        "audience": _FRIDAY_AUDIENCE,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                resp2.raise_for_status()
                data2 = resp2.json()
                token = data2.get("access_token", "")
                expires_in = data2.get("expires_in", 3600)
                if not token:
                    raise ValueError(f"No access_token in step2 response: {resp2.text[:200]}")
                self._token = token
                self._token_expires = time.time() + expires_in - 60
                return self._token
            except Exception as e:
                if self._log_errors:
                    logger.warning("Failed to get OAuth token: %s", e)
                return ""

    def _post(self, path: str, payload: dict) -> None:
        token = self._get_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = httpx.post(
                f"{self._base}{path}",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            if resp.is_success:
                logger.info("%s ok: %s", path, resp.text[:200])
            else:
                logger.warning("%s failed: %s %s | payload: %s",
                               path, resp.status_code, resp.text[:300],
                               json.dumps(payload, ensure_ascii=False)[:300])
        except Exception as e:
            if self._log_errors:
                logger.warning("%s error: %s | payload: %s", path, e,
                               json.dumps(payload, ensure_ascii=False)[:300])

    def report_span(self, span: dict) -> None:
        logger.info("report_span called: %s", span.get("span_type"))
        span_type = span.get("span_type", "turn")
        kind = _KIND_MAP.get(span_type, "CUSTOM")
        attrs = span.get("attributes") or {}
        model_name = attrs.get("model")

        usage: dict = {}
        output = span.get("output")
        if isinstance(output, dict) and "usage" in output:
            u = output["usage"]
            usage = {
                "promptTokens": u.get("prompt_tokens"),
                "completionTokens": u.get("completion_tokens"),
                "totalTokens": u.get("total_tokens"),
            }

        # Friday requires: numeric traceId, UUID spanId, bare model name
        numeric_trace_id = _to_numeric_trace_id(span.get("trace_id", ""))
        span_uuid = _to_uuid(span.get("span_id", ""))
        parent_uuid = _to_uuid(span.get("parent_span_id", "")) if span.get("parent_span_id") else None
        raw_model = (model_name or "").split("/", 1)[-1] if model_name else ""

        # agentId / conversationId / modelName go into attributes, not top-level
        span_attrs: dict = {
            "agentId": self._agent_id,
            "conversationId": span.get("session_id", ""),
        }
        if raw_model:
            span_attrs["modelName"] = raw_model

        start_payload: dict = {
            "traceId": numeric_trace_id,
            "spanId": span_uuid,
            "kind": kind,
            "name": f"{span_type}:{attrs.get('tool_name') or attrs.get('model') or span_type}",
            "startTime": _to_ms(span.get("start_time")),
            "input": _safe_json(span.get("input")),
            "attributes": span_attrs,
        }
        if parent_uuid:
            start_payload["parentSpanId"] = parent_uuid

        end_payload: dict = {
            "traceId": numeric_trace_id,
            "spanId": span_uuid,
            "kind": kind,
            "endTime": _to_ms(span.get("end_time")),
            "status": "FAILED" if span.get("status") == "error" else "SUCCESS",
            "output": _safe_json(output),
            "attributes": span_attrs,
        }
        if parent_uuid:
            end_payload["parentSpanId"] = parent_uuid
        if usage:
            end_payload.update(usage)

        def _send():
            logger.info("start payload: %s", json.dumps(start_payload, ensure_ascii=False))
            self._post("/tracing/v1/openapi/start/span", start_payload)
            self._post("/tracing/v1/openapi/end/span", end_payload)
            logger.info("upload done: traceId=%s", numeric_trace_id)

        threading.Thread(target=_send, daemon=True).start()


def setup(context: PluginContext) -> PluginHooks:
    cfg = context.config
    agent_id = cfg.get("agent_id", "").strip()

    if not agent_id:
        logger.warning(
            "agent_id 未配置，插件已加载但不会上报。"
            "请编辑 ~/.agentkit/workspace/plugins/friday-tracing/plugin.toml，填写 agent_id。"
            "获取方式：https://aigc.sankuai.com/app/appList/appListV2List"
        )
        return PluginHooks()

    client_id = cfg.get("client_id", "").strip()
    client_secret = cfg.get("client_secret", "").strip()
    if not client_id or not client_secret:
        logger.warning(
            "client_id / client_secret 未配置，请求可能因鉴权失败而被拒绝。"
            "获取方式：https://friday.sankuai.com/budget/serviceManage"
        )

    client = _FridayClient(
        base_url=cfg.get("base_url", "https://aigc.sankuai.com"),
        agent_id=agent_id,
        client_id=client_id,
        client_secret=client_secret,
        timeout_ms=int(cfg.get("timeout_ms", 5000)),
        log_errors=bool(cfg.get("log_errors", True)),
    )

    logger.info("已启动，agent_id=%s | Trace: https://friday.sankuai.com/app/observation/traceManagement", agent_id)

    return PluginHooks(on_span_end=client.report_span)
