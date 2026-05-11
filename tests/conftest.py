"""Shared test fixtures for AgentKit."""

from __future__ import annotations

import pytest

from agentkit.config.models import (
    AgentKitConfig,
    CLIConfig,
    ContextConfig,
    MemoryConfig,
    ModelConfig,
    ModelOptions,
    OrchestrationConfig,
    ToolsConfig,
)
from agentkit.model.types import Message, ToolCall


@pytest.fixture
def default_config():
    """Default AgentKit configuration for testing."""
    return AgentKitConfig()


@pytest.fixture
def sample_messages():
    """A realistic conversation message list."""
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="What time is it?"),
        Message(
            role="assistant",
            content="Let me check the time for you.",
            tool_calls=[
                ToolCall(id="tc_001", name="get_current_time", arguments={"timezone_name": "UTC"})
            ],
        ),
        Message(role="tool", content="2026-05-05 10:00:00 UTC", tool_call_id="tc_001", name="get_current_time"),
        Message(role="assistant", content="The current time is 10:00 AM UTC."),
    ]


@pytest.fixture
def sample_tool_call():
    """A sample ToolCall."""
    return ToolCall(id="tc_test", name="calculate", arguments={"expression": "2+2"})
