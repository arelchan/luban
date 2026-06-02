"""Build and inject system messages from context files."""

from __future__ import annotations

import os
import platform
from datetime import date

from agentkit import APP_NAME
from agentkit.memory.short_term import ShortTermMemory
from agentkit.model.types import Message


class ContextInjector:
    """Builds system messages from loaded context files and injects into memory."""

    def build_system_messages(
        self,
        context: dict[str, str | None],
        tools: list[dict] | None = None,
        skills: list | None = None,
        profile_text: str | None = None,
        model_name: str | None = None,
    ) -> list[Message]:
        """Build a single system message from all context sources.

        Sections (separated by ---):
        1. soul.md      → Personality/identity definition
        2. agents.md    → Task instructions and capabilities
        3. tools        → Dynamic tool list (generated from actual loaded tools)
        4. skills       → Available skill commands (progressive disclosure: name + trigger only)
        5. profile_text → Long-term memory profile (caller-prepared string, optional)
        6. memory.md    → Cross-session remembered facts
        7. environment  → Dynamic runtime info (date, platform, cwd, model)
        """
        sections: list[str] = []

        if context.get("soul"):
            sections.append(context["soul"].strip())
        if context.get("agents"):
            sections.append(context["agents"].strip())

        # Dynamic tool guide
        if tools:
            sections.append(self._build_tool_guide(tools))

        # Skills directory (progressive disclosure — just trigger + description)
        if skills:
            sections.append(self._build_skills_guide(skills))

        # Long-term memory profile
        if profile_text and profile_text.strip():
            sections.append(f"# 用户画像（长期记忆）\n\n{profile_text.strip()}")

        if context.get("memory"):
            sections.append(f"# Long-term Memory\n\n{context['memory'].strip()}")

        if not sections:
            sections.append(f"You are {APP_NAME}, a helpful CLI assistant.")

        # Dynamic environment section (always appended last)
        sections.append(self._build_environment(model_name))

        combined = "\n\n---\n\n".join(sections)
        return [Message(role="system", content=combined)]

    def inject(
        self,
        context: dict[str, str | None],
        memory: ShortTermMemory,
        tools: list[dict] | None = None,
        skills: list | None = None,
        profile_text: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """Load context and inject as system messages into short-term memory."""
        system_messages = self.build_system_messages(
            context, tools=tools, skills=skills, profile_text=profile_text, model_name=model_name,
        )
        memory.set_system_messages(system_messages)

    @staticmethod
    def _build_environment(model_name: str | None = None) -> str:
        """Build dynamic environment section with runtime info."""
        cwd = os.getcwd()
        shell = os.environ.get("SHELL", "unknown").rsplit("/", 1)[-1]
        os_version = platform.platform(terse=True)
        today = date.today().isoformat()

        lines = [
            "# Environment",
            "",
            f"- Date: {today}",
            f"- Working directory: {cwd}",
            f"- Platform: {platform.system().lower()}",
            f"- Shell: {shell}",
            f"- OS: {os_version}",
        ]
        if model_name:
            lines.append(f"- Model: {model_name}")
        lines.append(f"- Knowledge cutoff: January 2025")
        return "\n".join(lines)

    @staticmethod
    def _build_tool_guide(tools: list[dict]) -> str:
        """Build a dynamic tool reference guide grouped by usage scenario."""
        native = {t["name"]: t for t in tools if t.get("source") == "native"}
        mcp = [t for t in tools if t.get("source", "").startswith("mcp:")]

        # Define scenario groups with the tools that belong to each
        scenarios = [
            ("文件操作", ["read_file", "write_file", "edit_file", "list_directory"],
             "修改前必须先 read_file；小改用 edit_file，整体覆写才用 write_file"),
            ("搜索", ["glob_files", "grep_files"],
             "已知文件名 → glob_files；搜内容 → grep_files。禁止用 run_command 执行 find/grep/cat/ls"),
            ("Shell", ["run_command"],
             "仅当无对应内置工具时使用；危险命令（rm -rf / force push）执行前向用户确认"),
            ("Web", ["web_fetch", "web_search"],
             "获取网页内容 → web_fetch；搜索信息 → web_search"),
            ("任务管理", ["task_create", "task_update", "task_get", "task_list"],
             "3 步以上的任务先用 task_create 拆解，逐个 in_progress → completed"),
            ("记忆", ["memory_get_profile", "memory_keyword", "memory_search"],
             "需要用户背景 → memory_get_profile；精确查 → memory_keyword；语义查 → memory_search。不要每轮调用"),
            ("子代理", ["spawn_agent", "resume_agent"],
             "独立子任务并行处理或委派专项工作 → spawn_agent；迭代上限后继续 → resume_agent"),
            ("会话与自省", ["rename_session", "introspect_info", "introspect_source"],
             "查看运行时信息 → introspect_info；读 AgentKit 源码 → introspect_source"),
            ("工具", ["get_current_time", "calculate"],
             "需要当前时间或精确算术时使用"),
        ]

        lines = ["# Available Tools\n"]
        lines.append("## 使用原则")
        lines.append("- 修改文件前必须先 `read_file`，禁止盲改")
        lines.append("- 多个独立调用必须并行发出（同一轮）")
        lines.append("- 搜索优先级：已知路径 → `read_file` > 按名 → `glob_files` > 按内容 → `grep_files`")
        lines.append("- 不可逆操作前向用户确认\n")

        # Emit grouped native tools
        for group_name, tool_names, hint in scenarios:
            present = [native[n] for n in tool_names if n in native]
            if not present:
                continue
            lines.append(f"## {group_name}")
            lines.append(f"> {hint}")
            for t in present:
                lines.append(f"- `{t['name']}`: {t['description']}")
            lines.append("")

        # Any native tools not covered by scenarios
        covered = set()
        for _, names, _ in scenarios:
            covered.update(names)
        uncovered = [native[n] for n in native if n not in covered]
        if uncovered:
            lines.append("## 其他")
            for t in uncovered:
                lines.append(f"- `{t['name']}`: {t['description']}")
            lines.append("")

        # MCP tools grouped by server
        if mcp:
            lines.append("## MCP 扩展工具")
            by_server: dict[str, list[dict]] = {}
            for t in mcp:
                server = t.get("source", "mcp:unknown").removeprefix("mcp:")
                by_server.setdefault(server, []).append(t)
            for server, server_tools in by_server.items():
                lines.append(f"\n### {server}")
                for t in server_tools:
                    lines.append(f"- `{t['name']}`: {t['description']}")
            lines.append("")

        lines.append("> 不在上述列表中的工具名 = 未加载，不要尝试调用。")
        return "\n".join(lines)

    @staticmethod
    def _build_skills_guide(skills: list) -> str:
        """Build a short skills directory for progressive disclosure.

        Only trigger + description are shown; full prompt is injected on invocation.
        The model can suggest skills to the user but cannot invoke them directly.
        """
        lines = ["# Available Skills\n"]
        lines.append("Skills 是预置的工作流模板（.md 文件）。用户输入 trigger 时自动展开执行。")
        lines.append("你也可以主动使用：用 `introspect_source` 读取 skill 文件内容，将 `$ARGUMENTS` 替换为实际参数后按指令执行。\n")

        builtin = [s for s in skills if getattr(s, "source", "") == "builtin"]
        user = [s for s in skills if getattr(s, "source", "") == "user"]

        if builtin:
            lines.append("## 内置")
            for s in builtin:
                lines.append(f"- `{s.trigger}` — {s.description}")
            lines.append("")

        if user:
            lines.append("## 用户自定义")
            for s in user:
                lines.append(f"- `{s.trigger}` — {s.description}")
            lines.append("")

        return "\n".join(lines)
