"""Tests for agentkit.config — models, loader."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentkit.config.models import (
    AgentKitConfig,
    CLIConfig,
    ContextConfig,
    LongTermMemoryConfig,
    MCPServerConfig,
    MemoryConfig,
    ModelConfig,
    ModelOptions,
    OrchestrationConfig,
    ProviderConfig,
    SubAgentConfig,
    ToolsConfig,
)


# ─── Config Models (defaults) ───


class TestConfigModels:
    def test_model_options_defaults(self):
        opts = ModelOptions()
        assert opts.temperature == 0.7
        assert opts.max_tokens == 4096
        assert opts.thinking is False
        assert opts.thinking_budget == 10000
        assert opts.context_window == 200000

    def test_model_config_defaults(self):
        mc = ModelConfig()
        assert "anthropic" in mc.default
        assert mc.api_keys == {}
        assert mc.base_url is None

    def test_tools_config_defaults(self):
        tc = ToolsConfig()
        assert tc.enable_native is True
        assert tc.mcp_servers == []

    def test_mcp_server_config(self):
        srv = MCPServerConfig(name="fs", command="npx", args=["-y", "@mcp/filesystem"])
        assert srv.name == "fs"
        assert srv.enabled is True
        assert srv.env == {}

    def test_memory_config_defaults(self):
        mc = MemoryConfig()
        assert mc.short_term_max_messages == 50
        assert mc.short_term_max_tokens == 100000
        assert mc.long_term.enabled is True

    def test_long_term_memory_config(self):
        lt = LongTermMemoryConfig()
        assert lt.trigger == "every_n_turns"
        assert lt.trigger_value == 10
        assert lt.extraction_prompt is None

    def test_context_config_defaults(self):
        cc = ContextConfig()
        assert cc.watch_for_changes is True
        assert "agents.md" in cc.agents_file

    def test_orchestration_config(self):
        oc = OrchestrationConfig()
        assert oc.max_iterations == 100
        assert oc.parallel_tool_calls is True
        assert oc.sub_agents == []

    def test_sub_agent_config(self):
        sa = SubAgentConfig(name="coder", description="Writes code")
        assert sa.model is None  # Inherit from parent
        assert sa.tools == []

    def test_cli_config_defaults(self):
        cc = CLIConfig()
        assert cc.language == "zh"
        assert cc.show_tool_calls is True

    def test_provider_config(self):
        p = ProviderConfig(
            name="meituan",
            base_url="https://aigc.sankuai.com/v1/openai/native",
            api_key="sk-test",
            format="openai",
            models=["aws.claude-sonnet-4.6", "aws.claude-opus-4.7"],
        )
        assert p.name == "meituan"
        assert p.format == "openai"
        assert len(p.models) == 2

    def test_provider_config_defaults(self):
        p = ProviderConfig(name="test", base_url="https://test.com")
        assert p.api_key == ""
        assert p.format == "openai"
        assert p.models == []

    def test_model_config_with_providers(self):
        mc = ModelConfig(
            default="aws.claude-sonnet-4.6",
            providers=[
                ProviderConfig(
                    name="mt",
                    base_url="https://test.com",
                    models=["aws.claude-sonnet-4.6", "aws.claude-opus-4.7"],
                )
            ],
        )
        assert len(mc.providers) == 1
        assert mc.providers[0].name == "mt"

    def test_model_config_backward_compat(self):
        """Legacy config with base_url + api_keys should still work."""
        mc = ModelConfig(
            default="anthropic/claude",
            base_url="https://proxy.test",
            api_keys={"anthropic": "sk-abc"},
        )
        assert mc.base_url == "https://proxy.test"
        assert mc.providers == []

    def test_full_config_defaults(self):
        config = AgentKitConfig()
        assert config.model.default is not None
        assert config.tools.enable_native is True
        assert config.cli.language == "zh"


# ─── Config Loader ───


class TestConfigLoader:
    def test_load_nonexistent_returns_default(self):
        from agentkit.config.loader import load_config

        config = load_config(Path("/tmp/nonexistent_agentkit_config.toml"))
        assert isinstance(config, AgentKitConfig)
        assert config.cli.language == "zh"

    def test_save_and_load(self):
        from agentkit.config.loader import load_config, save_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            config = AgentKitConfig(
                model=ModelConfig(default="openai/gpt-4o"),
                cli=CLIConfig(language="en"),
            )
            save_config(config, path)

            loaded = load_config(path)
            assert loaded.model.default == "openai/gpt-4o"
            assert loaded.cli.language == "en"

    def test_save_creates_parent_dirs(self):
        from agentkit.config.loader import save_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sub" / "dir" / "config.toml"
            save_config(AgentKitConfig(), path)
            assert path.exists()

    def test_round_trip_model_options(self):
        from agentkit.config.loader import load_config, save_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            config = AgentKitConfig(
                model=ModelConfig(
                    options=ModelOptions(
                        temperature=0.5,
                        max_tokens=8192,
                        thinking=True,
                        thinking_budget=5000,
                        context_window=128000,
                    )
                )
            )
            save_config(config, path)
            loaded = load_config(path)
            assert loaded.model.options.temperature == 0.5
            assert loaded.model.options.thinking is True
            assert loaded.model.options.context_window == 128000

    def test_round_trip_providers(self):
        from agentkit.config.loader import load_config, save_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            config = AgentKitConfig(
                model=ModelConfig(
                    default="aws.claude-sonnet-4.6",
                    providers=[
                        ProviderConfig(
                            name="meituan",
                            base_url="https://aigc.sankuai.com/v1/openai/native",
                            api_key="sk-test",
                            format="openai",
                            models=["aws.claude-sonnet-4.6", "aws.claude-opus-4.7"],
                        )
                    ],
                )
            )
            save_config(config, path)
            loaded = load_config(path)
            assert len(loaded.model.providers) == 1
            assert loaded.model.providers[0].name == "meituan"
            assert loaded.model.providers[0].format == "openai"
            assert "aws.claude-opus-4.7" in loaded.model.providers[0].models
