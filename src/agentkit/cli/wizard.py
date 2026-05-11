"""First-run configuration wizard with language selection and step navigation."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel

from agentkit.config.defaults import DEFAULT_AGENTS_MD, DEFAULT_MEMORY_MD, DEFAULT_SOUL_MD
from agentkit.config.loader import CONFIG_FILE, load_config, save_config
from agentkit import APP_NAME
from agentkit.config.models import AgentKitConfig, CLIConfig, EmbeddingConfig, ModelConfig, ProviderConfig, WebSearchConfig


# ─── Sentinel for "go back" ───
class _GoBack:
    pass


GO_BACK = _GoBack()


# ─── Internationalization ───

TEXTS = {
    "zh": {
        "back_hint": "[dim]输入 b 返回上一步[/]",
        "back_msg": "已返回上一步",
        "at_first": "已在第一步",
        "welcome_title": f"欢迎使用 {APP_NAME}",
        "welcome_body": "让我们完成初始配置。\n\n[bold]必填[/]：模型提供商 + API Key\n[dim]可选[/]：搜索引擎、Embedding（可跳过，跳过后不再提示）",
        "step1_title": "步骤 1/3 — 选择模型提供商",
        "step1_desc": f"{APP_NAME} 需要连接一个大语言模型来工作。请选择你使用的模型服务商：",
        "step1_opt1": "Anthropic（Claude 系列模型）",
        "step1_opt2": "OpenAI（GPT 系列模型）",
        "step1_opt3": "本地模型（Ollama，无需联网）",
        "step1_prompt": "请选择 [1/2/3]：",
        "step1_error": "请输入 1、2 或 3",
        "step1_done": "已选择：{provider}",
        "step2_title": "步骤 2/3 — 填写 API Key",
        "step2_desc": "API Key 是你访问 {provider} 模型服务的凭证。\n   你可以在 {provider} 官网的控制台中创建和获取。",
        "step2_prompt": "请粘贴你的 API Key：",
        "step2_required": "API Key 不能为空，请粘贴你的 Key。",
        "step2_done": "API Key 已保存",
        "step2_ollama_title": "步骤 2/3 — Ollama 地址",
        "step2_ollama_desc": "请确保 Ollama 已在本地运行。\n   如果使用默认地址 http://localhost:11434，直接按 Enter。",
        "step2_ollama_prompt": "Ollama 服务地址：",
        "step2_ollama_done": "Ollama 已配置",
        "step3_title": "步骤 3/3 — API 接口地址",
        "step3_desc": "如果你通过第三方代理或公司内网访问模型服务，需要填写接口地址。\n   如果你直接使用 {provider} 官方服务，按 Enter 跳过即可。",
        "step3_prompt": "接口地址（按 Enter 跳过）：",
        "step3_done_url": "接口地址：{url}",
        "step3_done_default": "使用官方默认地址",
        "step3_skip": "步骤 3/3 — 本地模型无需配置接口地址",
        "done_config": "配置已保存 → {path}",
        "done_created": "已创建 → {path}",
        "done_title": "配置完成！",
        "done_body": (
            "配置文件：{config_path}\n"
            "工作目录：{workspace_path}\n"
            "  ├── soul.md    （Agent 人格，可自定义）\n"
            "  ├── agents.md  （任务指令，可自定义）\n"
            "  ├── memory.md  （长期记忆，自动维护）\n"
            "  ├── skills/    （自定义 Skills / 命令）\n"
            "  └── plugins/   （扩展插件，空目录）\n\n"
            "你可以随时编辑这些文件来调整 Agent 的行为。\n\n"
            f"正在启动 {APP_NAME}..."
        ),
    },
    "en": {
        "back_hint": "[dim]Enter b to go back[/]",
        "back_msg": "Going back",
        "at_first": "Already at first step",
        "welcome_title": f"Welcome to {APP_NAME}",
        "welcome_body": "Let's complete the initial setup.\n\n[bold]Required[/]: Model provider + API Key\n[dim]Optional[/]: Search engine, Embedding (skip to never be asked again)",
        "step1_title": "Step 1/3 — Choose model provider",
        "step1_desc": f"{APP_NAME} needs a large language model to work. Choose your provider:",
        "step1_opt1": "Anthropic (Claude models)",
        "step1_opt2": "OpenAI (GPT models)",
        "step1_opt3": "Local model (Ollama, no internet needed)",
        "step1_prompt": "Your choice [1/2/3]: ",
        "step1_error": "Please enter 1, 2, or 3",
        "step1_done": "Selected: {provider}",
        "step2_title": "Step 2/3 — Enter API Key",
        "step2_desc": "The API Key authenticates your access to {provider}'s model service.\n   You can create one in {provider}'s developer console.",
        "step2_prompt": "Paste your API Key: ",
        "step2_required": "API Key cannot be empty. Please paste your key.",
        "step2_done": "API Key saved",
        "step2_ollama_title": "Step 2/3 — Ollama Address",
        "step2_ollama_desc": "Make sure Ollama is running locally.\n   Press Enter to use the default address http://localhost:11434.",
        "step2_ollama_prompt": "Ollama service address: ",
        "step2_ollama_done": "Ollama configured",
        "step3_title": "Step 3/3 — API Endpoint",
        "step3_desc": "If you access the model via a proxy or corporate network, enter the endpoint URL.\n   If you use {provider}'s official API directly, just press Enter to skip.",
        "step3_prompt": "Endpoint URL (Enter to skip): ",
        "step3_done_url": "Endpoint: {url}",
        "step3_done_default": "Using official default endpoint",
        "step3_skip": "Step 3/3 — Local model, no endpoint needed",
        "done_config": "Config saved → {path}",
        "done_created": "Created → {path}",
        "done_title": "Setup complete!",
        "done_body": (
            "Config: {config_path}\n"
            "Workspace: {workspace_path}\n"
            "  ├── soul.md    (Agent personality, customizable)\n"
            "  ├── agents.md  (Task instructions, customizable)\n"
            "  ├── memory.md  (Long-term memory, auto-maintained)\n"
            "  ├── skills/    (Custom skills / commands)\n"
            "  └── plugins/   (Extension plugins, empty)\n\n"
            "You can edit these files anytime to customize your Agent.\n\n"
            f"Starting {APP_NAME}..."
        ),
    },
}


def needs_setup() -> bool:
    """Check if mandatory setup is incomplete.

    Mandatory: model provider + API key (or Ollama base_url).
    Optional steps (embedding, web search) are tracked in cli.skipped_optional_setup
    and never trigger the wizard again once skipped.
    """
    if not CONFIG_FILE.exists():
        return True

    config = load_config(CONFIG_FILE)

    # Local models don't need API keys
    if config.model.default.startswith("ollama/"):
        return False

    # Must have an API key
    return not bool(config.model.api_keys)


async def _prompt(
    session: PromptSession,
    prompt_text: str,
    is_password: bool = False,
) -> str | _GoBack:
    """Prompt user, return GO_BACK if they type 'b'."""
    value = await session.prompt_async(prompt_text, is_password=is_password)
    if value.strip().lower() == "b":
        return GO_BACK
    return value


async def run_wizard(console: Console) -> AgentKitConfig:
    """Interactive first-run configuration wizard with step navigation."""
    session: PromptSession[str] = PromptSession()

    # ─── Language Selection ───
    console.print()
    console.print(Panel(
        f"[bold]{APP_NAME} Setup[/]\n\n"
        "请选择语言 / Please select your language：",
        border_style="blue",
    ))
    console.print()
    console.print("   [cyan]1)[/] 中文")
    console.print("   [cyan]2)[/] English")
    console.print()

    while True:
        lang_choice = await session.prompt_async("   [1/2]: ")
        lang_choice = lang_choice.strip() or "1"
        if lang_choice in ("1", "2"):
            break
        console.print("   [red]请输入 1 或 2 / Please enter 1 or 2[/]")

    lang = "zh" if lang_choice == "1" else "en"
    t = TEXTS[lang]

    console.print()
    console.print(Panel(
        f"[bold green]{t['welcome_title']}[/]\n\n{t['welcome_body']}",
        border_style="green",
    ))

    # ─── Step state ───
    choice = ""
    api_keys: dict[str, str] = {}
    base_url: str | None = None
    step = 1

    while step <= 3:

        # ─── Step 1: Model Provider ───
        if step == 1:
            console.print()
            console.print(f"[bold]{t['step1_title']}[/]")
            console.print(f"   {t['step1_desc']}")
            console.print()
            console.print(f"   [cyan]1)[/] {t['step1_opt1']}")
            console.print(f"   [cyan]2)[/] {t['step1_opt2']}")
            console.print(f"   [cyan]3)[/] {t['step1_opt3']}")
            console.print()

            valid = False
            while not valid:
                result = await _prompt(session, f"   {t['step1_prompt']}")
                if isinstance(result, _GoBack):
                    console.print(f"   [dim]{t['at_first']}[/]")
                    continue
                choice = result.strip() or "1"
                if choice in ("1", "2", "3"):
                    valid = True
                else:
                    console.print(f"   [red]{t['step1_error']}[/]")

            provider_display = {"1": "Anthropic", "2": "OpenAI", "3": "Ollama"}[choice]
            console.print(f"\n   [green]✓[/] {t['step1_done'].format(provider=provider_display)}")
            step = 2
            continue

        # ─── Step 2: API Key ───
        if step == 2:
            api_keys = {}

            if choice in ("1", "2"):
                provider_key = "anthropic" if choice == "1" else "openai"
                provider_display = "Anthropic" if choice == "1" else "OpenAI"

                console.print()
                console.print(f"[bold]{t['step2_title']}[/]")
                console.print(f"   {t['step2_desc'].format(provider=provider_display)}")
                console.print(f"   {t['back_hint']}")
                console.print()

                while True:
                    result = await _prompt(session, f"   {t['step2_prompt']}", is_password=True)
                    if isinstance(result, _GoBack):
                        break
                    if result.strip():
                        api_keys[provider_key] = result.strip()
                        break
                    console.print(f"   [red]{t['step2_required']}[/]")

                if isinstance(result, _GoBack):
                    console.print(f"   [dim]{t['back_msg']}[/]")
                    step = 1
                    continue

                console.print(f"   [green]✓[/] {t['step2_done']}")

            else:
                # Ollama
                console.print()
                console.print(f"[bold]{t['step2_ollama_title']}[/]")
                console.print(f"   {t['step2_ollama_desc']}")
                console.print(f"   {t['back_hint']}")
                console.print()
                result = await _prompt(session, f"   {t['step2_ollama_prompt']}")
                if isinstance(result, _GoBack):
                    console.print(f"   [dim]{t['back_msg']}[/]")
                    step = 1
                    continue
                if result.strip():
                    base_url = result.strip()
                console.print(f"   [green]✓[/] {t['step2_ollama_done']}")

            step = 3
            continue

        # ─── Step 3: Base URL / Endpoint ───
        if step == 3:

            if choice in ("1", "2"):
                provider_display = "Anthropic" if choice == "1" else "OpenAI"

                console.print()
                console.print(f"[bold]{t['step3_title']}[/]")
                console.print(f"   {t['step3_desc'].format(provider=provider_display)}")
                console.print(f"   {t['back_hint']}")
                console.print()

                result = await _prompt(session, f"   {t['step3_prompt']}")
                if isinstance(result, _GoBack):
                    console.print(f"   [dim]{t['back_msg']}[/]")
                    step = 2
                    continue

                if result.strip():
                    base_url = result.strip()
                    console.print(f"   [green]✓[/] {t['step3_done_url'].format(url=base_url)}")
                else:
                    base_url = None
                    console.print(f"   [green]✓[/] {t['step3_done_default']}")

            else:
                console.print()
                console.print(f"   [dim]{t['step3_skip']}[/]")

            step = 4  # Exit loop

    # ─── Load existing config to preserve skipped_optional_setup ───
    existing_config = load_config(CONFIG_FILE) if CONFIG_FILE.exists() else None
    skipped = list(existing_config.cli.skipped_optional_setup) if existing_config else []

    # ─── Optional: Web Search ───
    brave_api_key = ""
    if "web_search" not in skipped:
        if lang == "zh":
            console.print()
            console.print("[bold]（可选）配置搜索引擎 — 用于 web_search 工具[/]")
            console.print("   默认使用 Bing 免费搜索（国内可用）。")
            console.print("   配置 Brave Search API Key 可获得更稳定、更高质量的搜索结果。")
            console.print("   跳过后不再弹此提示，可随时在 config.toml 中配置。")
            ws_choice = (await _prompt(session, "   配置 Brave Search API Key？[y/N]：")).strip().lower()
        else:
            console.print()
            console.print("[bold](Optional) Configure Search Engine[/]")
            console.print("   Default: Bing HTML scraping (no key, works globally).")
            console.print("   Brave Search API key gives better quality and stability.")
            console.print("   Skip to never be asked again; configure anytime in config.toml.")
            ws_choice = (await _prompt(session, "   Configure Brave Search API key? [y/N]: ")).strip().lower()

        if ws_choice == "y":
            prompt_text = "   Brave Search API Key：" if lang == "zh" else "   Brave Search API Key: "
            brave_api_key = (await _prompt(session, prompt_text)).strip()
            console.print(f"   [green]✓[/] {'Brave Search 已配置' if lang == 'zh' else 'Brave Search configured'}")
        else:
            skipped.append("web_search")

    # ─── Optional: Embedding config ───
    embed_enabled = False
    embed_base_url = ""
    embed_api_key = ""
    embed_model = "text-embedding-3-small"
    # Preserve existing embedding config if already set
    if existing_config and existing_config.memory.embedding.enabled:
        ec = existing_config.memory.embedding
        embed_enabled = True
        embed_base_url = ec.base_url
        embed_api_key = ec.api_key
        embed_model = ec.model

    if "embedding" not in skipped and not embed_enabled:
        if lang == "zh":
            console.print()
            console.print("[bold]（可选）配置 Embedding 模型 — 用于长期记忆向量检索[/]")
            console.print("   未配置时长期记忆功能不可用。需要 OpenAI 兼容的 embedding 接口。")
            console.print("   跳过后不再弹此提示，可随时在 config.toml 中配置。")
            emb_choice = (await _prompt(session, "   配置 Embedding？[y/N]：")).strip().lower()
        else:
            console.print()
            console.print("[bold](Optional) Configure Embedding model — for long-term memory[/]")
            console.print("   Without this, long-term memory is disabled. Needs OpenAI-compatible endpoint.")
            console.print("   Skip to never be asked again; configure anytime in config.toml.")
            emb_choice = (await _prompt(session, "   Configure Embedding? [y/N]: ")).strip().lower()

        if emb_choice == "y":
            embed_enabled = True
            if lang == "zh":
                embed_base_url = (await _prompt(session, "   Embedding 接口地址（Enter 使用 OpenAI 官方）：")).strip()
                embed_api_key = (await _prompt(session, "   Embedding API Key：")).strip()
                embed_model_input = (await _prompt(session, f"   模型名称（Enter 使用 {embed_model}）：")).strip()
            else:
                embed_base_url = (await _prompt(session, "   Embedding endpoint (Enter for OpenAI): ")).strip()
                embed_api_key = (await _prompt(session, "   Embedding API Key: ")).strip()
                embed_model_input = (await _prompt(session, f"   Model name (Enter for {embed_model}): ")).strip()
            if embed_model_input:
                embed_model = embed_model_input
            console.print(f"   [green]✓[/] Embedding {'已配置' if lang == 'zh' else 'configured'}: {embed_model}")
        else:
            skipped.append("embedding")

    # ─── Build and Save Config ───
    model_map = {
        "1": "aws.claude-sonnet-4.6",
        "2": "gpt-4o",
        "3": "ollama/llama3",
    }
    default_model = model_map.get(choice, model_map["1"])

    # Build providers list (new-style config)
    providers: list[ProviderConfig] = []
    if base_url and choice in ("1", "2"):
        provider_name = "anthropic-proxy" if choice == "1" else "openai-proxy"
        api_key_val = next(iter(api_keys.values()), "")
        providers.append(ProviderConfig(
            name=provider_name,
            base_url=base_url.rstrip("/"),
            api_key=api_key_val,
            format="openai",
            models=[default_model],
        ))

    from agentkit.config.models import MemoryConfig
    config = AgentKitConfig(
        model=ModelConfig(
            default=default_model,
            providers=providers,
            # Also set legacy fields for backward compat
            api_keys=api_keys,
            base_url=base_url.rstrip("/") if base_url else None,
        ),
        cli=CLIConfig(language=lang, skipped_optional_setup=skipped),
        memory=MemoryConfig(
            embedding=EmbeddingConfig(
                enabled=embed_enabled,
                base_url=embed_base_url,
                api_key=embed_api_key,
                model=embed_model,
            )
        ),
        tools=__import__("agentkit.config.models", fromlist=["ToolsConfig"]).ToolsConfig(
            web_search=WebSearchConfig(
                brave_api_key=brave_api_key,
            )
        ),
    )

    workspace_path = Path(config.context.workspace_dir).expanduser().resolve()

    save_config(config)
    console.print(f"\n[green]{t['done_config'].format(path=CONFIG_FILE)}[/]")

    # Create workspace structure
    workspace_path.mkdir(parents=True, exist_ok=True)
    # Empty dirs for user extensions
    (workspace_path / config.context.skills_dir).mkdir(exist_ok=True)
    (workspace_path / config.context.plugins_dir).mkdir(exist_ok=True)

    for filename, content in [
        ("soul.md", DEFAULT_SOUL_MD),
        ("agents.md", DEFAULT_AGENTS_MD),
        ("memory.md", DEFAULT_MEMORY_MD),
    ]:
        file_path = workspace_path / filename
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")
            console.print(f"[green]{t['done_created'].format(path=file_path)}[/]")

    console.print()
    console.print(Panel(
        f"[bold green]{t['done_title']}[/]\n\n"
        + t["done_body"].format(config_path=CONFIG_FILE, workspace_path=workspace_path),
        border_style="green",
    ))
    console.print()

    return config
