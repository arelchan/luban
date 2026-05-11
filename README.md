# Luban

一个模块化的 CLI Agent 框架，用于学习和构建基于大语言模型的智能体。

## 特性

- **多模型适配** — 基于 LiteLLM + 直连 httpx 双模式，支持 Anthropic、OpenAI、本地模型及自定义代理；支持 Extended Thinking 模式
- **工具系统** — 23 个内置工具（文件读写编辑、Shell、搜索、Web 抓取/搜索、任务管理、子 Agent 派发、会话管理、自查等）+ MCP 协议兼容；搜索引擎支持 Brave Search API（需配置 key）或 Bing 免费爬取
- **记忆管理** — 短期对话历史 + 智能上下文压缩（LLM Task-based 结构化摘要）+ 长期结构化记忆（用户画像/客观事实/经验教训，需配置 Embedding）
- **上下文注入** — `soul.md`（人格）/ `agents.md`（指令）/ `memory.md`（记忆）/ Skills 目录（渐进式披露）启动时注入，watchdog 实时热更新
- **编排引擎** — think-act-observe Agent Loop + 工具式子 Agent（`spawn_agent` / `resume_agent`），支持并行派发、完全隔离、工具白名单、轮次中断恢复
- **插件系统** — 目录扫描式插件加载（`~/.agentkit/workspace/plugins/`），支持 `on_span_end` / `on_session_end` 钩子，内置 friday-tracing 示例插件
- **可观测性** — OpenTelemetry 风格 Tracing（`/log` 仪表盘）+ 开发者 Audit Log（`~/.agentkit/audit.log`，JSONL 格式，可 `tail -f`）
- **数据管理** — Trace/Session/Audit 数据可配置留存周期，启动时自动清理过期数据
- **国际化** — 支持中文/English 双语，`/lang` 命令切换，首次运行向导语言持久化
- **CLI 产品形态** — Rich 渲染 + prompt_toolkit 异步输入（`/` 自动补全）、首次运行配置向导、启动时显示模型参数和上下文使用率

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/yourname/agentkit.git
cd agentkit

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装（开发模式）
pip install -e ".[dev]"
```

### 运行

```bash
luban
```

首次运行会进入配置向导，引导你完成：
1. 选择语言（中文/English）
2. 选择模型供应商并配置 API Key
3. 配置 Base URL（自定义代理可选）
4. 配置搜索引擎（Brave API key，可跳过）
5. 配置 Embedding 模型（用于长期记忆，可跳过）

配置完成后自动进入对话模式。

### 配置文件

配置保存在 `~/.agentkit/config.toml`，示例：

```toml
[model]
default = "aws.claude-sonnet-4.6"

# 多供应商配置（推荐）
[[model.providers]]
name = "meituan"                                      # 供应商名称
base_url = "https://aigc.sankuai.com/v1/openai/native" # API 端点
api_key = "your-api-key"                               # API Key
format = "openai"                                      # API 格式：openai | anthropic
models = ["aws.claude-sonnet-4.6", "aws.claude-opus-4.6", "aws.claude-opus-4.7"]

[model.options]
temperature = 0.7
max_tokens = 4096
context_window = 200000

[tools]
enable_native = true

[tools.web_search]
# engine = "auto"          # auto | brave | bing
# brave_api_key = ""       # 配置后使用 Brave Search API

[memory]
short_term_max_messages = 50
short_term_max_tokens = 100000

[memory.long_term]
enabled = true

[memory.embedding]
# enabled = true
# model = "text-embedding-3-small"
# base_url = ""
# api_key = ""

[data]
trace_retention_days = 30    # 0 = 永久保留
session_retention_days = 0
audit_retention_days = 30
```

### 内置命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/tools` | 查看已加载的工具 |
| `/sessions` | 查看历史会话列表 |
| `/session new` | 保存当前会话并新建 |
| `/title [name]` | 查看/修改当前会话标题 |
| `/skills` | 查看已加载的 Skills |
| `/commit [msg]` | Skill：分析 git diff 并提交 |
| `/review [file]` | Skill：Code Review |
| `/explain [file]` | Skill：解释代码 |
| `/find-skills [keyword]` | Skill：搜索和发现 OpenClaw Skills |
| `/self [question]` | Skill：自查 — 回答关于 Luban 自身的问题 |
| `/memory` | 查看记忆状态 |
| `/compress` | 手动压缩上下文（LLM 生成结构化摘要替代旧消息） |
| `/extract` | 手动触发长期记忆抽取（需配置 Embedding） |
| `/model <name>` | 临时切换模型 |
| `/models` | 查看所有可用模型 |
| `/usage` | 查看当前会话 token 消耗（含缓存命中） |
| `/log` | 打开 Tracing 仪表盘（浏览器） |
| `/lang [zh\|en]` | 切换界面语言（中文/English） |
| `/restart` | 重启 Luban |
| `/clear` | 清除对话历史 |
| `/exit` | 退出 |

## 工作空间

```
~/.agentkit/
├── config.toml
├── audit.log           # 开发者审计日志（JSONL，可 tail -f）
├── plugins.log         # 插件运行日志
└── workspace/          # 用户自定义内容
    ├── soul.md         # Agent 人格（可自定义）
    ├── agents.md       # 任务指令（可自定义）
    ├── memory.md       # 长期记忆（自动维护）
    ├── memories.json   # 结构化长期记忆（需 Embedding）
    ├── skills/         # 自定义 Skills（目录包格式）
    │   └── <name>/SKILL.md
    └── plugins/        # 扩展插件（空目录）
        └── <name>/
            ├── plugin.toml
            └── __init__.py
```

## 插件系统

Luban 支持通过插件扩展功能。插件放在 `~/.agentkit/workspace/plugins/<name>/`，启动时自动加载。

```python
# 插件入口 __init__.py 示例
from agentkit.plugins.manager import PluginContext, PluginHooks

def setup(context: PluginContext) -> PluginHooks:
    def on_span_end(span: dict) -> None:
        # 每个 tracing span 结束时触发
        pass

    return PluginHooks(on_span_end=on_span_end)
```

内置示例插件：`examples/plugins/friday-tracing/`（将 trace 数据上报到 Friday 平台）。

## 架构

```
src/agentkit/
├── audit.py            # 开发者审计日志（单例，JSONL）
├── cleanup.py          # 数据清理（trace/session/audit 留存）
├── config/             # 配置层：Pydantic 模型 + TOML 读写
├── model/              # 模型层：LiteLLM + httpx 双模式 + Embedder
├── tools/
│   └── builtin/        # 内置工具包（按功能域拆分）
│       ├── files.py    # read/write/edit/list_directory
│       ├── shell.py    # run_command
│       ├── search.py   # glob/grep
│       ├── web.py      # web_fetch/web_search
│       ├── tasks.py    # task_create/update/get/list
│       ├── memory.py   # memory_get_profile/keyword/search
│       ├── agents.py   # spawn_agent/resume_agent
│       └── session.py  # rename_session/introspect_*
├── memory/             # 记忆层：短期 + 压缩 + 长期结构化
├── context/            # 上下文层：文件加载 + watchdog 热更新
├── orchestration/      # 编排层：Agent Loop + Sub-Agent Executor
├── plugins/            # 插件系统：目录扫描 + hook 分发
├── session/            # 会话层：多会话管理 + 持久化
├── skills/             # Skills 层：目录包格式，入口 SKILL.md
│   └── builtin/
│       └── <name>/SKILL.md
├── tracing/            # 可观测层：OpenTelemetry 风格 Span
├── dashboard/          # 仪表盘：本地 Web UI
└── cli/                # CLI 层：REPL + 渲染 + 向导
```

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 模型适配 | LiteLLM + httpx | LiteLLM 覆盖主流模型，httpx 直连保证自定义代理可靠性 |
| 工具协议 | MCP Python SDK | Model Context Protocol 是工具互操作标准 |
| 配置校验 | Pydantic v2 | 类型安全的配置模型 |
| 配置格式 | TOML (tomli-w) | Python 生态标准配置格式 |
| 终端渲染 | Rich | Markdown 渲染、流式输出 |
| 终端输入 | prompt_toolkit | 异步输入、历史记录、/ 命令补全 |
| 文件监控 | watchdog | 跨平台文件系统事件 |
| 重试机制 | tenacity | 指数退避处理 API 限流 |

## 开发

```bash
# 运行测试
pytest

# 代码检查
ruff check src/

# 格式化
ruff format src/

# 查看实时审计日志
tail -f ~/.agentkit/audit.log | python3 -m json.tool

# 过滤错误
grep '"status":"error"' ~/.agentkit/audit.log | python3 -m json.tool
```

## License

MIT
