"""hello-plugin — 最简示例插件。

安装方式：
    cp -r examples/plugins/hello-plugin ~/.agentkit/workspace/plugins/
"""

from __future__ import annotations

from agentkit.plugins.manager import PluginContext, PluginHooks


def setup(context: PluginContext) -> PluginHooks:
    print(f"[hello-plugin] loaded (Luban {context.app_version})")

    def on_span_end(span: dict) -> None:
        span_type = span.get("span_type", "?")
        duration = span.get("duration_ms")
        dur_str = f"{duration:.0f}ms" if duration is not None else "?"
        print(f"[hello-plugin] span_end: {span_type} ({dur_str})")

    def on_session_end(session_id: str) -> None:
        print(f"[hello-plugin] session ended: {session_id}")

    return PluginHooks(
        on_span_end=on_span_end,
        on_session_end=on_session_end,
    )
