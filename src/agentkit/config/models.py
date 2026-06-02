"""Pydantic configuration models for AgentKit."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ModelOptions(BaseModel):
    temperature: float = 0.7
    max_tokens: int = 4096
    thinking: bool = False  # Extended thinking (Anthropic)
    thinking_budget: int = 10000  # Max thinking tokens when thinking=True
    context_window: int = 200000  # Model context window size


class ProviderConfig(BaseModel):
    name: str                    # Provider identifier, e.g. "meituan"
    base_url: str                # API endpoint URL
    api_key: str = ""            # API key for this provider
    format: Literal["openai", "anthropic"] = "openai"  # API format
    models: list[str] = Field(default_factory=list)     # Available model IDs


class ModelConfig(BaseModel):
    default: str = "anthropic/aws.claude-sonnet-4.6"
    providers: list[ProviderConfig] = Field(default_factory=list)
    options: ModelOptions = Field(default_factory=ModelOptions)
    # Legacy fields (deprecated, kept for backward compatibility)
    api_keys: dict[str, str] = Field(default_factory=dict)
    base_url: str | None = None
    available: list[str] = Field(default_factory=list)


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class WebSearchConfig(BaseModel):
    engine: Literal["auto", "brave", "bing"] = "auto"
    # auto = brave if api_key set, else bing HTML scrape
    brave_api_key: str = ""   # https://api.search.brave.com/


class ToolPermissionsConfig(BaseModel):
    """Tool execution permission levels.

    - auto_allow: tools that execute without user confirmation (safe, read-only)
    - require_confirm: tools that need user approval before execution (writes, shell)
    - deny: tools that are completely blocked

    Tools not listed in any category default to auto_allow.
    """
    auto_allow: list[str] = Field(default_factory=lambda: [
        "read_file", "glob_files", "grep_files", "list_directory",
        "get_current_time", "calculate", "web_search", "web_fetch",
        "task_create", "task_update", "task_get", "task_list",
        "memory_get_profile", "memory_keyword", "memory_search",
        "introspect_info", "introspect_source", "rename_session",
    ])
    require_confirm: list[str] = Field(default_factory=lambda: [
        "run_command", "write_file", "edit_file",
    ])
    deny: list[str] = Field(default_factory=list)


class ToolsConfig(BaseModel):
    enable_native: bool = True
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    permissions: ToolPermissionsConfig = Field(default_factory=ToolPermissionsConfig)


class LongTermMemoryConfig(BaseModel):
    enabled: bool = True
    storage_file: str = "~/.agentkit/memory.md"
    memories_file: str = "~/.agentkit/workspace/memories.json"
    extraction_model: str = ""  # Empty = use main model; set to a cheaper model to reduce cost
    trigger: Literal["every_n_turns", "on_session_end", "manual"] = "every_n_turns"
    trigger_value: int = 10
    extraction_prompt: str | None = None  # Custom prompt template, None = use default


class EmbeddingConfig(BaseModel):
    enabled: bool = False
    provider: str = "openai"          # openai | ollama | custom
    model: str = "text-embedding-3-small"
    base_url: str = ""                # Custom proxy endpoint
    api_key: str = ""
    dimensions: int = 1536


class MemoryConfig(BaseModel):
    short_term_max_messages: int = 50
    short_term_max_tokens: int = 100000
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


class ContextConfig(BaseModel):
    workspace_dir: str = "~/.agentkit/workspace"
    agents_file: str = "agents.md"
    soul_file: str = "soul.md"
    memory_file: str = "memory.md"
    skills_dir: str = "skills"     # relative to workspace_dir (user custom skills/commands)
    plugins_dir: str = "plugins"  # relative to workspace_dir
    watch_for_changes: bool = True


class SubAgentConfig(BaseModel):
    name: str
    description: str
    model: str | None = None  # None = inherit from parent
    soul_file: str | None = None
    tools: list[str] = Field(default_factory=list)  # Tool name filter


class OrchestrationConfig(BaseModel):
    max_iterations: int = 100
    parallel_tool_calls: bool = True
    sub_agents: list[SubAgentConfig] = Field(default_factory=list)


class CLIConfig(BaseModel):
    language: Literal["zh", "en"] = "zh"
    show_tool_calls: bool = True
    show_token_usage: bool = False
    history_file: str = "~/.agentkit/history.txt"
    # Tracks which optional setup steps user has explicitly skipped
    skipped_optional_setup: list[str] = Field(default_factory=list)


class DataConfig(BaseModel):
    trace_retention_days: int = 30    # days to keep trace files, 0 = forever
    session_retention_days: int = 0   # days to keep session files, 0 = forever
    audit_retention_days: int = 30    # days to keep audit log files


class AgentKitConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    cli: CLIConfig = Field(default_factory=CLIConfig)
    data: DataConfig = Field(default_factory=DataConfig)
