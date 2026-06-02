"""Internationalization — all user-facing CLI text in Chinese and English."""

from __future__ import annotations

from typing import Literal

Lang = Literal["zh", "en"]

# ---------- CLI REPL texts ----------

TEXTS: dict[str, dict[str, str]] = {
    "zh": {
        # Banner
        "banner_hint": "输入 /help 查看命令，/exit 退出",
        # Config loaded
        "config_loaded": "配置：{path}",
        # Startup info
        "model_label": "模型：{model}",
        "model_params": "参数：temp={temp} | max_tokens={max_tokens} | thinking={thinking} | 上下文窗口={ctx}k",
        "tools_label": "工具：{tools}",
        # Help table
        "help_title": "命令列表",
        "help_col_cmd": "命令",
        "help_col_desc": "说明",
        "help_help": "显示此帮助信息",
        "help_tools": "查看已加载的工具",
        "help_memory": "查看记忆状态",
        "help_extract": "手动触发长期记忆抽取",
        "help_model": "查看当前模型",
        "help_model_set": "临时切换模型",
        "help_log": "在浏览器中打开追踪仪表盘",
        "help_lang": "查看当前语言",
        "help_lang_set": "切换语言",
        "help_restart": "重启 {app_name}",
        "help_clear": "清除对话历史",
        "help_usage": "查看当前会话 token 消耗",
        "help_exit": "退出 {app_name}",
        # Command feedback
        "cleared": "对话已清除。",
        "memory_status": "轮次：{turns} | 消息：{messages} | 长期记忆：{long_term}",
        "usage_header": "Token 消耗：",
        "usage_input": "  输入：{total}（缓存命中：{cache_read} | 新建缓存：{cache_creation} | 未缓存：{uncached}）",
        "usage_output": "  输出：{output}",
        "usage_total": "  合计：{all}",
        "memory_enabled": "已启用",
        "memory_disabled": "未启用（需配置 Embedding）",
        "extracting": "正在抽取长期记忆...",
        "extract_done": "记忆已更新（{chars} 字符）",
        "extract_empty": "无内容可抽取。",
        "model_switched": "模型已切换为：{model}",
        "model_current": "当前模型：{model}",
        "dashboard_opened": "仪表盘已打开：{url}",
        "lang_switched": "语言已切换为：中文",
        "lang_current": "当前语言：中文 (zh)。输入 /lang en 切换为 English",
        "restarting": "正在重启 {app_name}...",
        "unknown_cmd": "未知命令：{cmd}",
        "goodbye": "再见！",
        # Status indicators
        "status_thinking": "思考中...",
        "status_tool_running": "执行工具：{name}...",
        # Tool call display
        "tool_calling": ">>> 调用：{name}({args})",
        "tool_result": "<<< {name}：{result}",
        # Session management
        "session_list_header": "历史会话",
        "session_prompt": "   输入编号继续，Enter 新建，d<编号> 删除（如 d1）：",
        "session_new": "新建会话",
        "session_resumed": "已恢复会话：{title}（{turns} 轮）",
        "session_created": "新建会话：{id}",
        "session_list_empty": "无历史会话",
        "session_deleted": "已删除会话：{title}",
        "session_delete_invalid": "无效编号：{n}",
        "help_sessions": "查看历史会话列表",
        "help_session_new": "保存当前会话并新建",
        "help_title": "查看/修改当前会话标题",
        "help_skills": "查看已加载的 Skills",
        "title_updated": "会话标题已更新：{title}",
        "title_current": "当前会话标题：{title}",
        # Context compression
        "context_compressing": "正在压缩上下文...",
        "context_compressed": "上下文已压缩（{before} → {after}）",
        "context_no_need": "当前上下文较短，无需压缩",
        "help_compress": "手动压缩上下文（摘要替代旧消息）",
        # Errors
        "error_prefix": "错误：",
    },
    "en": {
        # Banner
        "banner_hint": "Type /help for commands, /exit to quit",
        # Config loaded
        "config_loaded": "Config: {path}",
        # Startup info
        "model_label": "Model: {model}",
        "model_params": "Params: temp={temp} | max_tokens={max_tokens} | thinking={thinking} | context={ctx}k",
        "tools_label": "Tools: {tools}",
        # Help table
        "help_title": "Commands",
        "help_col_cmd": "Command",
        "help_col_desc": "Description",
        "help_help": "Show this help message",
        "help_tools": "List available tools",
        "help_memory": "Show memory status",
        "help_extract": "Force long-term memory extraction",
        "help_model": "Show current model",
        "help_model_set": "Switch model temporarily",
        "help_log": "Open tracing dashboard in browser",
        "help_lang": "Show current language",
        "help_lang_set": "Switch language",
        "help_restart": "Restart {app_name}",
        "help_clear": "Clear conversation history",
        "help_usage": "Show token usage for current session",
        "help_exit": "Exit {app_name}",
        # Command feedback
        "cleared": "Conversation cleared.",
        "memory_status": "Turns: {turns} | Messages: {messages} | Long-term: {long_term}",
        "usage_header": "Token Usage:",
        "usage_input": "  Input: {total} (cache hit: {cache_read} | cache write: {cache_creation} | uncached: {uncached})",
        "usage_output": "  Output: {output}",
        "usage_total": "  Total: {all}",
        "memory_enabled": "enabled",
        "memory_disabled": "disabled (Embedding not configured)",
        "extracting": "Extracting long-term memory...",
        "extract_done": "Memory updated ({chars} chars)",
        "extract_empty": "Nothing to extract.",
        "model_switched": "Model switched to: {model}",
        "model_current": "Current model: {model}",
        "dashboard_opened": "Dashboard opened: {url}",
        "lang_switched": "Language switched to: English",
        "lang_current": "Current language: English (en). Type /lang zh to switch to 中文",
        "restarting": "Restarting {app_name}...",
        "unknown_cmd": "Unknown command: {cmd}",
        "goodbye": "Goodbye!",
        # Status indicators
        "status_thinking": "Thinking...",
        "status_tool_running": "Running tool: {name}...",
        # Tool call display
        "tool_calling": ">>> Calling: {name}({args})",
        "tool_result": "<<< {name}: {result}",
        # Session management
        "session_list_header": "Sessions",
        "session_prompt": "   Enter number to resume, Enter for new, d<n> to delete (e.g. d1): ",
        "session_new": "New session",
        "session_resumed": "Resumed session: {title} ({turns} turns)",
        "session_created": "New session: {id}",
        "session_list_empty": "No previous sessions",
        "session_deleted": "Deleted session: {title}",
        "session_delete_invalid": "Invalid number: {n}",
        "help_sessions": "List all sessions",
        "help_session_new": "Save current session and start new",
        "help_title": "View/rename current session title",
        "help_skills": "List loaded skills",
        "title_updated": "Session title updated: {title}",
        "title_current": "Current session title: {title}",
        # Context compression
        "context_compressing": "Compressing context...",
        "context_compressed": "Context compressed ({before} → {after})",
        "context_no_need": "Context is short, no compression needed",
        "help_compress": "Manually compress context (summarize old messages)",
        # Errors
        "error_prefix": "Error: ",
    },
}


def t(key: str, lang: Lang = "zh", **kwargs: str) -> str:
    """Get a translated string, with optional format kwargs."""
    from agentkit import APP_NAME

    text = TEXTS.get(lang, TEXTS["zh"]).get(key, key)
    # Always inject app_name so {app_name} in templates gets resolved
    kwargs.setdefault("app_name", APP_NAME)
    if "{" in text:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text


# ---------- Tool description translations ----------

TOOL_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "zh": {
        "read_file": "读取文件内容，支持行偏移和行数限制",
        "write_file": "创建或覆盖文件，自动创建父目录",
        "edit_file": "通过精确字符串匹配替换来编辑文件",
        "run_command": "执行 Shell 命令并返回输出",
        "glob_files": "按 glob 模式搜索文件（如 '**/*.py'）",
        "grep_files": "用正则表达式搜索文件内容",
        "list_directory": "列出目录内容，显示文件类型和大小",
        "get_current_time": "获取当前日期和时间",
        "calculate": "安全地计算数学表达式",
        "web_fetch": "抓取 URL 并返回文本内容，HTML 自动转纯文本",
        "web_search": "搜索网页并返回标题、URL 和摘要",
        "rename_session": "重命名当前会话标题",
        "introspect_info": "获取 {app_name} 运行时信息（工具、Skills、命令、配置等）",
        "introspect_source": "读取 {app_name} 自身源码或文档",
        "task_create": "创建任务，用于追踪多步骤工作进度",
        "task_update": "更新任务状态（in_progress / completed / cancelled）",
        "task_list": "列出当前所有任务及其状态",
        "spawn_agent": "派生隔离的子 Agent 执行独立子任务，支持并行调用",
        "resume_agent": "恢复因轮次上限中断的子 Agent，从断点继续执行",
        "memory_get_profile": "获取用户画像偏好（技术栈/工作习惯/背景等）",
        "memory_keyword": "按关键词精确搜索长期记忆条目",
        "memory_search": "按语义相似度搜索长期记忆（需配置 embedding；否则降级为关键词搜索）",
        "cron_create": "创建定时任务（频率 + 生命周期 + prompt）",
        "cron_list": "查看当前所有定时任务",
        "cron_delete": "删除指定的定时任务",
    },
    "en": {},  # Empty = use original English docstrings
}


def tool_desc(name: str, lang: Lang = "zh") -> str | None:
    """Get localized tool description, or None to use the default."""
    return TOOL_DESCRIPTIONS.get(lang, {}).get(name)
