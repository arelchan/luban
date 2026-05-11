# Luban 插件开发指南

Luban 支持通过插件扩展功能。插件放在 `~/.agentkit/workspace/plugins/<name>/` 目录，启动时自动扫描加载。

---

## 目录结构

```
~/.agentkit/workspace/plugins/
└── my-plugin/          # 插件目录名即插件 ID
    ├── plugin.toml     # 元信息 + 配置（必须）
    └── __init__.py     # 插件入口（必须）
```

---

## plugin.toml

```toml
[plugin]
name = "my-plugin"
version = "1.0.0"
description = "插件说明"
enabled = true          # false 则跳过加载

[config]
# 插件自定义配置，可在 setup() 里通过 context.config 读取
api_key = ""
base_url = "https://example.com"
```

---

## __init__.py 接口约定

每个插件必须实现 `setup(context) -> PluginHooks` 函数：

```python
from agentkit.plugins.manager import PluginContext, PluginHooks

def setup(context: PluginContext) -> PluginHooks:
    """
    context.plugin_id  — 插件目录名
    context.config     — plugin.toml 的 [config] 部分（dict）
    context.app_version — Luban 版本
    context.plugins_dir — ~/.agentkit/workspace/plugins/ 的绝对路径
    """
    api_key = context.config.get("api_key", "")

    def on_span_end(span: dict) -> None:
        # span 结构与 /api/spans 返回的 span_dict 相同
        # span["span_id"], span["span_type"], span["input"], span["output"] 等
        pass

    def on_session_end(session_id: str) -> None:
        # 会话正常退出时调用
        pass

    return PluginHooks(
        on_span_end=on_span_end,
        on_session_end=on_session_end,
    )
```

---

## 可用 Hooks

| Hook | 触发时机 | 参数 |
|------|---------|------|
| `on_span_end(span_dict)` | 每个 span 结束时（turn/llm/tool/compression/subagent 均触发） | `dict` — `span.to_dict()` 的结果 |
| `on_session_end(session_id)` | CLI 会话正常退出时 | `str` — session id |

**注意**：
- Hook 函数不能抛出异常（Luban 会捕获并忽略）
- Hook 是同步调用的，耗时操作建议在后台线程/队列里做
- 插件不应 import Luban 内部模块，只依赖 `PluginContext` 和 `PluginHooks`

---

## span_dict 字段说明

`on_span_end` 收到的 `span_dict` 结构：

```python
{
    "span_id": "abc123",
    "trace_id": "def456",
    "session_id": "sess_xxx",
    "parent_span_id": "ghi789",   # None 表示根 span
    "span_type": "turn",          # turn | llm | tool | compression | subagent
    "start_time": 1715000000.0,   # Unix timestamp (seconds)
    "end_time": 1715000001.5,
    "duration_ms": 1500.0,
    "status": "ok",               # ok | error
    "attributes": {               # span_type 相关的附加属性
        "turn_index": 1,
        "model": "anthropic/...", # llm span 有
        "tool_name": "read_file", # tool span 有
        "agent_id": "sa_xxx",     # subagent span 有
    },
    "input": ...,                 # 输入内容（类型因 span_type 而异）
    "output": ...,                # 输出内容
}
```

---

## 示例插件

参见同目录下：
- `hello-plugin/` — 最简插件，打印每个 span 类型
- `friday-tracing/` — 上报 trace 数据到 Friday 平台（美团内网）
