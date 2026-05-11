# Luban — 产品与技术设计文档

## 1. 产品定位

Luban 是一个面向开发者的本地 CLI Agent 框架，目标是：

- 帮助开发者理解 Agent 框架的核心架构（模型、工具、记忆、上下文、编排）
- 提供可独立运行的 Agent 产品形态
- 最小化依赖，优先复用成熟开源组件

**不是**：不是 LangChain 的竞品，不追求大而全，不做 SaaS 平台。

---

## 2. 架构总览

十一层架构，自底向上：

```
┌─────────────────────────────────────────────────┐
│  CLI 层 (Rich + prompt_toolkit + / 补全)         │ ← 用户交互
├─────────────────────────────────────────────────┤
│  Skills 层 (目录包 Prompt Templates)               │ ← 预定义技能
├─────────────────────────────────────────────────┤
│  插件层 (Plugin Manager + Hooks)                 │ ← 用户扩展
├─────────────────────────────────────────────────┤
│  会话层 (Session Store + 数据清理)               │ ← 多会话管理
├─────────────────────────────────────────────────┤
│  可观测层 (Tracing + Dashboard + Audit Log)      │ ← 可观测性
├─────────────────────────────────────────────────┤
│  编排层 (Agent Loop + Sub-Agent Executor)        │ ← 调度决策
├─────────────────────────────────────────────────┤
│  上下文层 (File Loader + Watchdog)               │ ← 人格/指令注入
├─────────────────────────────────────────────────┤
│  记忆层 (Short-term + Compression + Long-term)   │ ← 对话管理
├─────────────────────────────────────────────────┤
│  工具层 (@tool 包 + MCP Client)                  │ ← 能力扩展
├─────────────────────────────────────────────────┤
│  模型层 (LiteLLM + httpx Direct + Embedder)      │ ← LLM/Embedding
└─────────────────────────────────────────────────┘
```

---

## 3. 各层详细设计

### 3.1 模型层

#### 产品设计

**双模式架构**：支持多供应商多模型路由和零配置官方端点两种模式。

| 场景 | 调用方式 | 优势 |
|------|----------|------|
| 配置了 `providers`（推荐） | httpx 直连 | 多供应商多模型，根据模型名自动路由到对应 provider |
| 配置了 `base_url`（旧） | httpx 直连 | 向后兼容旧配置，单 base_url |
| 都未配置 | LiteLLM | 零配置接入 100+ 官方模型端点 |

**核心能力**：
- 多供应商路由：同时配置多个 API 端点（如公司内网、官方 API），按模型名自动选择 provider
- 双协议适配：同时支持 Anthropic Messages API 和 OpenAI Chat Completions 格式
- 流式输出：SSE 实时推送，支持文本流和工具调用流
- Extended Thinking：支持 Anthropic 的 thinking 模式，给模型更多"思考"空间
- Token 追踪：累计统计输入/输出/缓存命中/缓存创建 token 用量
- 上下文超限自愈：超出模型上下文窗口时自动触发压缩重试，用户无感知
- 重试容错：API 限流和瞬时错误自动指数退避重试
- 启动时显示模型参数（temperature、max_tokens、thinking 开关、上下文窗口）
- 动态 Prompt：`you (Xk/200k)>` 实时显示上下文使用量

#### 实现方案

**核心文件**：`client.py`、`types.py`、`token_counter.py`

**ModelClient**（`client.py`）：
- `_resolve_provider(model)` — 遍历 `providers` 列表，按 `models` 字段匹配路由
- SSE 容错：同时支持 `data: {...}` 和 `data:{...}` 两种格式
- tenacity 重试：指数退避 3 次
- Extended Thinking：`thinking=true` 时自动设置 temperature=1，传入 `thinking.budget_tokens`
- Token 跟踪：从 `message_start` 和 `message_delta` SSE 事件中提取 usage，区分 `cache_creation_tokens` / `cache_read_tokens`
- `ContextWindowExceeded` 异常统一 LiteLLM（`ContextWindowExceededError`）和直连模式（HTTP 400 含 "too long"/"token limit"/"context length"）

**数据类型**（`types.py`）：
- `Message` — 统一消息格式（role, content, tool_calls, tool_call_id）
- `ToolCall` — 工具调用（id, name, arguments）
- `StreamChunk` — 流式块（content_delta, tool_calls_delta, is_final）
- `ModelResponse` — 完整响应（content, tool_calls, usage, stop_reason）
- `TokenUsage` — token 用量（prompt_tokens, completion_tokens, cache_creation_tokens, cache_read_tokens）

### 3.2 工具层

#### 产品设计

**双通道工具系统**：

1. **原生工具**（23 个内置）：

   | 功能域 | 工具 |
   |--------|------|
   | 文件操作 | `read_file`, `write_file`, `edit_file`, `list_directory` |
   | 搜索 | `glob_files`, `grep_files` |
   | Shell | `run_command` |
   | Web | `web_fetch`, `web_search` |
   | 任务管理 | `task_create`, `task_update`, `task_get`, `task_list` |
   | 记忆 | `memory_get_profile`, `memory_keyword`, `memory_search` |
   | 子代理 | `spawn_agent`, `resume_agent` |
   | 会话与自省 | `rename_session`, `introspect_info`, `introspect_source` |
   | 工具 | `get_current_time`, `calculate` |

   - 工具描述支持 i18n（用户界面 `/tools` 显示中文描述，LLM Schema 保持英文）
   - `edit_file` 支持 `replace_all=True`，批量替换所有匹配字符串
   - `grep_files` 支持 `context` 参数（前后 N 行上下文）和 `max_results` 参数（默认 100）
   - `run_command` 默认 timeout 120s，支持 `background=True` 后台异步执行
   - 任务管理四件套：模型可在复杂多步骤任务中自主拆解和追踪进度
   - 子 Agent 派发：工具式调用，完全隔离上下文，支持工具白名单和并行派发

2. **MCP 工具**：连接外部 MCP Server，自动发现工具列表，命名空间隔离（`servername__toolname`）

#### 实现方案

**核心文件**：`native.py`、`mcp_client.py`、`manager.py`、`builtin/`（包，按功能域拆分子模块）

**@tool 装饰器**（`native.py`）：
- 自动从类型注解 + docstring 生成 OpenAI function calling JSON Schema
- 完整 docstring 作为 `function.description`（含 WHEN TO USE / WHEN NOT TO USE）
- Google-style Args 段解析为每个参数的 description
- 支持 sync 和 async 函数

**MCP Client**（`mcp_client.py`）：通过 stdio 或 SSE 连接 MCP Server 进程，`session.list_tools()` 发现工具

**ToolManager**（`manager.py`）：统一管理原生和 MCP 两类工具，对编排层暴露统一接口：
- `get_tool_schemas()` → OpenAI function calling 格式
- `execute_tool(name, arguments)` → 执行并返回结果

### 3.3 记忆层

#### 产品设计

记忆层分为三层：

1. **原始记忆** — 完整会话 log，持久化到磁盘，不加工
2. **短期记忆（对话历史）** — 当前会话的完整对话记录 + 上下文压缩
3. **长期记忆** — 从会话中提炼的结构化知识，跨会话持久化

**上下文压缩**：在不破坏历史核心对话内容的前提下减少上下文占用。

触发时机（3 种）：

| # | 触发方式 | 条件 | 行为 |
|---|---------|------|------|
| 1 | `/compress` 手动 | 用户输入命令 | 立即执行压缩 |
| 2 | API 超上下文错误 | 捕获上下文超限 | 压缩 → 重建 messages → 重试 LLM |
| 3 | 每轮结束后预防性 | 剩余 context < 5000 tokens | 自动压缩 |

压缩摘要格式（Task-based）：
- ✓ 已完成 Task：意图 + 决策 + 结论 + 涉及文件
- ⧖ 进行中 Task：意图 + 决策过程 + 当前进展 + 待解决
- ✗ 未完成 Task：意图 + 卡点 + 如需继续方向

"最近一轮"完整保留不参与压缩。CLI 显示 spinner + token 变化。

**长期记忆**：三种类型，跨会话持久化。

| 类型 | 含义 | 示例 |
|------|------|------|
| `profile` | 用户画像偏好 | "使用 Python 3.13，偏好 asyncio 风格" |
| `fact` | 客观事实 | "内网代理地址是 https://xxx" |
| `lesson` | 经验教训 | "修改代码必须同步更新 README 和 PRD" |

触发时机（自动）：压缩前、`/clear` 前、`/session new` 前、恢复历史会话前。手动：`/extract`。

检索方式（三个工具）：
- `memory_get_profile()` — 全量用户画像
- `memory_keyword(keyword)` — 关键词精确匹配
- `memory_search(query)` — 语义相似度检索（需 embedding）

Profile 全量注入 system prompt（条目少、高价值），fact/lesson 按需工具查询。

Embedding 未配置时优雅降级：只存文本，`memory_search` 回退为关键词搜索。

#### 实现方案

**核心文件**：`short_term.py`、`long_term.py`、`store.py`、`manager.py`、`prompts.py`

**ShortTermMemory**（`short_term.py`）：
- `full_log: List[Message]` — 维护完整会话日志
- System 消息始终保留，不参与压缩
- `_compressed_summary` — 压缩后替代旧消息的结构化摘要

**MemoryManager**（`manager.py`）：协调短期和长期记忆。
- 两阶段压缩：
  1. 预处理裁剪（无 LLM）— 截断长 tool result（>200 字截为 150 字）和长 assistant 回复（>500 字截为 300 字）
  2. LLM 结构化任务摘要 — 按任务切分生成摘要，替代旧消息
- 压缩作为独立 trace（非子 span），input 为压缩 prompt，output 为摘要
- 剩余 context 阈值：`_REMAINING_THRESHOLD = 5000`

**LongTermMemory**（`long_term.py`）：
- operations 增量机制：LLM 输出 add/update/merge/delete/skip JSON
- 向量预筛相似条目（cosine similarity > 0.85），交 LLM 判断合并策略
- confidence 机制：lesson 每次强化 +0.1

**MemoryStore**（`store.py`）：
- 存储：`~/.agentkit/workspace/memories.json`
- 每条：id、type、content、vector（可选）、source_session_id、created_at/updated_at

**Embedding 配置**（可选）：
```toml
[memory.embedding]
enabled = true
provider = "openai"
model = "text-embedding-3-small"
base_url = ""
api_key = ""
dimensions = 1536
```

### 3.4 上下文层

#### 产品设计

**系统上下文注入**：启动时从 workspace 加载多个来源，按优先级拼接为 system message：

| 段落 | 来源 | 用途 |
|------|------|------|
| 人格 | `soul.md` | Agent 身份和风格定义 |
| 指令 | `agents.md` | 高层行为规则（先读后改、并行调用、危险确认等） |
| 工具指南 | 动态生成 | 按场景分组的工具目录 + 使用优先级提示 |
| Skills 目录 | 动态生成 | trigger + description（渐进式披露） |
| 用户画像 | 长期记忆 profile | 个性化背景信息 |
| 跨会话记忆 | `memory.md` | 历史经验/事实 |

**agents.md 设计哲学**：只保留高层策略规则，具体工具使用规范下沉到每个工具的 docstring 中，避免重复维护。

**工具指南与 Skills 目录**：
- 工具指南按使用场景分组，每组附使用优先级提示——告诉模型"有哪些工具 + 何时用哪个"
- Skills 目录仅 trigger + description——模型需要时通过 `introspect_source` 读完整内容再执行

**子 Agent 系统**：
- 主模型通过 `spawn_agent` 工具自主决定何时派子任务
- 完全隔离：子 agent 独立上下文，不共享主对话历史
- 工具白名单：限制子 agent 可用工具范围
- 并行派发：一次 tool_calls 可同时派多个子 agent
- 轮次上限恢复：到达上限时返回结构化通知，主模型可 `resume_agent` 继续
- agent_id 标识：可按 ID 过滤 trace

**运行时热更新**：修改 workspace 文件后 1 秒内自动重载 system message，不中断对话。

#### 实现方案

**核心文件**：`loader.py`、`injector.py`、`watcher.py`

**ContextInjector**（`injector.py`）：
- `build_system_messages(context, tools, skills, profile_text)` — 拼接所有段落为单个 system message
- `_build_tool_guide(tools)` — 按 9 个场景组生成工具指南，uncovered 工具归入"其他"
- `_build_skills_guide(skills)` — 按 source 分组（内置/用户）展示 trigger + description

**ContextWatcher**（`watcher.py`）：
- watchdog Observer 监控 soul.md / agents.md / memory.md
- 去抖 1 秒（`_last_event_time` + 定时器线程）
- 触发时重新调用 `injector.inject()` 替换 system 消息

**子 Agent 实现**：
- `spawn_agent` 生成唯一 `agent_id`（`sa_xxxxxxxx`）
- 状态存于 `_runtime_context["subagent_states"]`（会话级，退出清空）
- `resume_agent` 通过 agent_id 取回 messages 继续执行
- 到达 `max_iterations` 返回 `[AGENT_LIMIT]` 结构化通知
- Tracing：`turn → subagent span → [turn, llm, tool...]` 三层结构

### 3.5 编排层

#### 产品设计

**Agent Loop**（think-act-observe 循环）：

```
用户输入 → [添加到记忆]
  → LLM(messages + tool_schemas)
    → 上下文超限？→ 压缩上下文 → 重试 LLM
    → 纯文本？→ 流式渲染输出，结束本轮
    → tool_calls？→ 执行工具 → 结果加入记忆 → 回到 LLM
  → 超过 max_iterations？→ 强制结束并警告
  → 本轮结束 → 剩余 context < 5k？→ 预防性压缩
```

- 流式输出：文本实时推送到终端
- 工具调用可视化：显示调用过程和结果
- 多工具并行：一次 LLM 响应可返回多个 tool_calls，并行执行
- 最大迭代保护：防止模型陷入死循环（默认 100 轮）

#### 实现方案

**核心文件**：`loop.py`、`agent.py`、`sub_agent.py`

**AgentLoop**（`loop.py`）：
- `run(messages)` → `(final_text, new_messages)` — 主循环入口
- 捕获 `ContextWindowExceeded` → 调用 `MemoryManager.compress()` → 重建 messages 重试
- 回调机制：`on_stream_delta`、`on_tool_start`、`on_tool_end`
- Tracing 埋点：自动记录 turn/llm/tool span
- `max_iterations` 到达时追加 `[SYSTEM]` 事件消息通知模型

### 3.6 可观测层

#### 产品设计

**Tracing**：OpenTelemetry 风格的调用链追踪，记录每轮对话的完整操作链路。

Span 类型：

| span_type | 含义 | input | output |
|-----------|------|-------|--------|
| `turn` | 一轮对话 | 用户消息 | 助手回复 |
| `llm` | 一次模型调用 | messages + tools | content + tool_calls + usage |
| `tool` | 一次工具执行 | name + arguments | result |
| `compression` | 一次上下文压缩 | 压缩 prompt | 结构化摘要 |

层级：`turn`（根） → 多个 `llm` 和 `tool` 子 span。`compression` 为独立根 trace。

**Dashboard（本地 Web UI）**：
- 暗色主题三栏布局：Trace 列表 | Span 列表 | 详情面板
- 3 秒自动刷新，保持页面状态（滚动、折叠）
- 类型色彩标签：Turn 蓝色、LLM 紫色、Tool 绿色
- Token 消耗展示：Session 累计 + 每轮消耗 + LLM span 完整 usage（含缓存命中/创建/未缓存）
- 通过 `/log` 命令打开浏览器访问

#### 实现方案

**核心文件**：`tracing/models.py`、`tracing/collector.py`、`dashboard/server.py`、`dashboard/template.py`

**Span 数据模型**（`models.py`）：
- `span_id` / `trace_id` / `session_id` / `parent_span_id` — 标识与关联
- `span_type`、`start_time` / `end_time`、`status`（ok/error）
- `attributes` — 扩展属性（模型名、工具名、agent_id 等）
- `input` / `output` — 类型相关数据

**SessionTracer**（`collector.py`）：
- 每日 JSONL 文件持久化：`~/.agentkit/sessions/traces/{session_id}/{date}.jsonl`
- span 结束时立即 append，dedup by span_id（last wins）
- 兼容读取 legacy `.json` 数组格式
- `on_span_end` hook：插件系统的 trace 转发入口
- 不侵入 ModelClient / ToolManager 接口

**Dashboard**（`server.py` + `template.py`）：
- stdlib `http.server` 后台线程，零外部依赖
- 数据 Hash 对比避免不必要的 DOM 重建

### 3.7 会话层

#### 产品设计

- 每个会话拥有独立的上下文窗口，会话间完全隔离
- 启动时用户选择"继续历史会话"或"新建会话"；无历史会话时自动新建
- 每轮对话后自动保存，退出时更新索引元数据
- `/sessions` 查看历史会话列表，`/session new` 保存并新建，`/title` 修改标题

#### 实现方案

**核心文件**：`models.py`、`store.py`

**存储结构**：
```
~/.agentkit/sessions/
├── index.json           # 会话索引（元数据列表）
├── sess_{id}.json       # 单个会话的完整消息记录
└── traces/<session_id>/ # Tracing 数据（按日期分文件）
```

**SessionStore API**（`store.py`）：
- `list_sessions()` — 按 `updated_at` 降序
- `create_session()` / `load_session()` / `save_messages()` / `delete_session()`
- `update_meta()` — 更新标题、轮次、时间等元信息

### 3.8 Skills 层

#### 产品设计

Skills 是预定义的工作流模板，用户输入 `/name [args]` 触发自动执行，模型也可主动读取并按指令执行。

**统一格式**（一个 skill = 一个目录包）：

```
<name>/
├── SKILL.md          # 入口文件（YAML frontmatter + prompt body）
├── references/       # 可选，附属参考文档
└── scripts/          # 可选，辅助脚本
```

**SKILL.md 格式**：

```markdown
---
name: commit
description: 分析 git diff 并生成 commit message 提交
---

请帮我完成一次 git commit。步骤如下：
1. 先执行 `git status` 和 `git diff --staged` ...
2. ...

用户参数：$ARGUMENTS
```

- YAML frontmatter 的 `name` 字段可选（缺省时以目录名为 skill 名）
- `description` 用于系统上下文中的 Skills 目录展示
- 正文是 prompt template，`$ARGUMENTS` 占位符接收用户参数

**来源优先级**（用户覆盖内置，同名时用户优先）：

1. 用户自定义：`~/.agentkit/workspace/skills/<name>/SKILL.md`
2. 内置：`src/agentkit/skills/builtin/<name>/SKILL.md`

**内置 Skills**：

| 命令 | 功能 |
|------|------|
| `/commit [msg]` | 分析 git diff，生成 commit message 并提交 |
| `/review [file]` | Code Review |
| `/explain [file]` | 解释代码段 |
| `/find-skills [keyword]` | 搜索和发现 OpenClaw Skills |
| `/self [question]` | 自查能力，基于源码和运行时状态回答关于自身的问题 |

**渐进式披露**：

- 系统上下文只注入 skills 目录（trigger + description），不含完整 prompt
- 模型需要时通过 `introspect_source` 读取完整 SKILL.md，替换 `$ARGUMENTS` 后按指令执行
- 用户直接输入 trigger 时自动展开执行

**执行流程**：

1. 用户输入以 `/` 开头 → 先匹配内置命令（/help, /exit 等）
2. 未命中 → 尝试匹配 Skill trigger（大小写不敏感）
3. 命中 → 替换 `$ARGUMENTS` → 作为 user message 执行 AgentLoop
4. 未命中 → 视为普通用户输入，发送给 LLM（不报错"未知命令"）

**设计原则**：只有精确匹配已知命令或 Skill 时才作为命令处理，否则一律作为正常对话输入。

#### 实现方案

**核心文件**：`models.py`、`loader.py`、`executor.py`、`builtin/<name>/SKILL.md`

**SkillDef 数据模型**（`models.py`）：
- `name: str` — skill 名称
- `description: str` — 简短描述
- `trigger: str` — 触发命令（`/name`）
- `prompt_template: str` — 完整 prompt body（含 `$ARGUMENTS`）
- `source: str` — 来源标识（`"builtin"` | `"user"`）

**SkillLoader**（`loader.py`）：
- `_scan_dir(directory)` — 扫描目录下所有子目录，筛选含 `SKILL.md` 的（忽略隐藏目录和无入口目录）
- `_parse_skill_md(path)` — 正则提取 YAML frontmatter（name、description）+ body
- `load_all()` — 先加载 builtin，再加载 user（同名覆盖）

**SkillExecutor**（`executor.py`）：
- `match(user_input)` — 按 trigger 匹配（大小写不敏感），返回 `(SkillDef, args_str)`
- `build_prompt(skill, args)` — 替换 `$ARGUMENTS`，无占位符时追加参数到末尾
- `list_skills()` — 返回所有已加载 skill

**系统上下文注入**（`context/injector.py` 的 `_build_skills_guide`）：
- 按 source 分组（内置 / 用户自定义），每条只展示 trigger + description

### 3.9 插件系统

#### 产品设计

让用户在不修改核心代码的情况下扩展功能，插件崩溃不影响主流程。

**插件结构**：
```
~/.agentkit/workspace/plugins/<name>/
├── plugin.toml   # 元信息 + 插件配置（enabled, [config] 段）
└── __init__.py   # 入口：setup(context) -> PluginHooks
```

**可用 Hook**：

| Hook | 触发时机 | 用途 |
|------|---------|------|
| `on_span_end(span_dict)` | 每个 tracing span 结束 | 实时 trace 转发（如上报 Friday） |
| `on_session_end(session_id)` | 会话正常退出 | 清理或汇总 |

**隔离原则**：
- 插件日志重定向到 `~/.agentkit/plugins.log`，不污染终端
- 插件 hook 异常被捕获，不传播到主流程
- 插件不能直接 import 框架内部模块

**示例**：`examples/plugins/friday-tracing/` — 将 trace 上报到 Friday 平台。

#### 实现方案

**核心文件**：`manager.py`

**PluginContext**（只读）：`plugin_id`、`config`（plugin.toml 的 [config] 段）、`app_version`、`plugins_dir`

**PluginHooks**：`on_span_end: Callable[[dict], None]`、`on_session_end: Callable[[str], None]`

**PluginManager**：
- `load_plugins(plugins_dir)` — 扫描目录，importlib 动态加载 `__init__.py`，调用 `setup()` 获取 hooks
- `dispatch_span_end(span_dict)` / `dispatch_session_end(session_id)` — 遍历所有已注册 hook，try/except 捕获异常
- 异常记录到 audit log + plugins.log，不 raise

---

### 3.10 Audit Log

#### 产品设计

框架维度的开发者审计日志，与 Tracing 系统互补：

| 系统 | 维度 | 用途 | 面向 |
|------|------|------|------|
| Tracing | 会话/span | 分析对话质量、调用链 | 产品/算法 |
| Audit Log | 框架事件 | 排查问题、溯源根因 | 开发者 |

JSONL 格式，按天轮转，`tail -f` 实时查看。

覆盖事件：启动/关闭、会话新建/恢复、插件加载、工具加载、Skills 加载、Agent Loop 全周期（turn/llm/tool 开始结束）、记忆压缩/提取、上下文重载、数据清理。

#### 实现方案

**核心文件**：`audit.py`

**事件结构**：
```json
{"ts":"2026-05-08T09:16:43.123Z","level":"INFO","component":"agent.loop",
 "action":"tool.call","status":"ok","data":{"name":"read_file"},"duration_ms":120.5}
```

**`audit(component, action, status, data, duration_ms)`** — 全局单例，写入 `~/.agentkit/audit.log`

**覆盖的 component → action**：
- `app` → `startup` / `startup.complete` / `shutdown` / `session.new` / `session.resume`
- `plugin.loader` → `plugin.load`
- `tool.manager` → `tools.loaded`
- `skill.loader` → `skills.loaded`
- `agent.loop` → `turn.start` / `turn.end` / `turn.max_iterations` / `llm.call` / `llm.done` / `llm.error` / `llm.context_exceeded` / `tool.call` / `tool.done` / `tool.error`
- `memory.manager` → `compress.start` / `compress.done` / `extract.start` / `extract.done` / `extract.error`
- `context.loader` → `context.reload`
- `cleanup` → `trace.cleanup` / `session.cleanup`

---

### 3.11 数据留存

#### 产品设计

启动时后台自动清理过期数据，不阻塞主流程。三类数据各自可配置留存天数（0 = 永久保留）。

```toml
[data]
trace_retention_days = 30
session_retention_days = 0
audit_retention_days = 30
```

#### 实现方案

**核心文件**：`cleanup.py`

清理逻辑（后台线程执行一次）：
- Trace：遍历 `traces/<session_id>/*.jsonl`（含 legacy `*.json`），按文件名日期判断是否过期；清理后空目录自动删除
- Session：遍历 `sess_*.json`，按文件修改时间判断；同步更新 index.json
- Audit log：由 `TimedRotatingFileHandler` 原生管理轮转

---

### 3.12 CLI 层

#### 产品设计

**REPL 交互**：
- 流式 Markdown 渲染、工具调用过程可视化
- `/` 自动弹出命令列表，支持实时过滤

**首次运行向导**：
- 语言选择（中文 / English）
- **必填步骤**：选模型供应商 → 填 API Key → 填 Base URL（未完成每次启动都弹）
- **可选步骤**（跳过后不再弹）：搜索引擎（Brave API key）、Embedding 模型
- 支持 'b' 回退上一步

**内置命令**：`/help`, `/tools`, `/sessions`, `/session new`, `/title [name]`, `/skills`, `/memory`, `/extract`, `/model`, `/model <name>`, `/models`, `/usage`, `/compress`, `/log`, `/lang`, `/lang zh|en`, `/restart`, `/clear`, `/exit`, `/quit`

**Skill 命令**（内置）：`/commit`, `/review`, `/explain`, `/find-skills`, `/self`（可通过用户 skill 目录扩展）

**国际化**：支持中文/英文，`/lang` 切换，语言持久化到 config.toml。

**系统事件通知**：关键运行时事件（模型切换、上下文压缩、文件热更新、插件加载/出错、记忆提取、迭代上限）注入对话历史，模型可实时感知环境变化。

#### 实现方案

**核心文件**：`app.py`、`renderer.py`、`wizard.py`、`i18n.py`

- `app.py` — REPL 主循环、组件初始化顺序、命令分发
- `renderer.py` — Rich 流式 Markdown 渲染 + 工具调用 panel
- `wizard.py` — 首次运行配置向导（必填/可选分离，完成后创建 workspace 目录结构）
- `i18n.py` — 双语字符串表 + 工具中文描述（`TOOL_DESCRIPTIONS`）

**事件注入**（`events.py`）：`emit_system_event(msg)` — 以 `[SYSTEM timestamp]` 前缀作为 user message 注入对话历史

---

## 4. 配置系统

**配置文件**: `~/.agentkit/config.toml`

**校验**: Pydantic v2 模型，所有字段带默认值和类型检查。

**配置模型层级**：
```
AgentKitConfig
├── ModelConfig (default, providers[], options, base_url*, api_keys*)
│   ├── ProviderConfig (name, base_url, api_key, format, models[])
│   └── ModelOptions (temperature, max_tokens, thinking, thinking_budget, context_window)
├── ToolsConfig (enable_native, mcp_servers, web_search)
│   └── WebSearchConfig (engine, brave_api_key)
├── MemoryConfig (short_term_max_messages, short_term_max_tokens, long_term, embedding)
│   ├── LongTermMemoryConfig (enabled, storage_file, memories_file, extraction_model, trigger, trigger_value)
│   └── EmbeddingConfig (enabled, provider, model, base_url, api_key, dimensions)
├── ContextConfig (workspace_dir, soul_file, agents_file, memory_file, skills_dir, plugins_dir, watch_for_changes)
├── OrchestrationConfig (max_iterations, parallel_tool_calls, sub_agents[])
│   └── SubAgentConfig (name, description, model, soul_file, tools[])
├── CLIConfig (language, show_tool_calls, show_token_usage, history_file, skipped_optional_setup[])
└── DataConfig (trace_retention_days, session_retention_days, audit_retention_days)
```

---

## 5. 工作空间与数据目录

```
~/.agentkit/
├── config.toml              # 主配置文件
├── history.txt              # 输入历史（prompt_toolkit）
├── audit.log                # 开发者审计日志（JSONL，按天轮转）
├── plugins.log              # 插件运行日志
├── sessions/                # 会话数据
│   ├── index.json           # 会话索引
│   ├── sess_<id>.json       # 单个会话消息历史
│   └── traces/<session_id>/ # Tracing 数据（JSONL，按日期分文件）
│       └── 2026-05-08.jsonl
└── workspace/               # 用户自定义内容（全部在此）
    ├── soul.md              # Agent 人格（可自定义）
    ├── agents.md            # 任务指令（可自定义）
    ├── memory.md            # 长期记忆 legacy（自动维护）
    ├── memories.json        # 结构化长期记忆（需配置 Embedding）
    ├── skills/              # 自定义 Skills（目录包格式）
    │   └── <name>/         # 每个 skill 一个目录
    │       ├── SKILL.md    # 入口（YAML frontmatter + prompt body）
    │       ├── references/ # 可选，附属参考文档
    │       └── scripts/    # 可选，辅助脚本
    └── plugins/             # 扩展插件（空目录，按需放）
        └── <name>/
            ├── plugin.toml
            └── __init__.py
```

---

## 6. 技术选型理由

| 选型 | 选用 | 不用 | 理由 |
|------|------|------|------|
| 模型适配 | LiteLLM + httpx | PydanticAI, LangChain | LiteLLM 够轻；httpx 保证自定义代理可靠 |
| 工具协议 | MCP SDK | LangChain Tools | MCP 是行业标准，生态丰富 |
| 记忆 | 自研 Markdown | mem0, 向量数据库 | 透明可控，适合学习，不需要向量检索的复杂度 |
| 配置 | Pydantic + TOML | YAML, JSON | TOML 是 Python 标准；Pydantic 类型安全 |
| CLI | Rich + prompt_toolkit | Click, Typer | 需要异步输入 + 高质量渲染，Click 不支持 |
| 重试 | tenacity | 手写 | 标准库，指数退避 + 条件重试开箱即用 |

---

## 7. 依赖清单

```toml
dependencies = [
    "litellm>=1.40",          # 多模型适配
    "httpx>=0.27",            # HTTP 直连（自定义代理）
    "mcp>=1.0",               # MCP 工具协议
    "pydantic>=2.0",          # 配置校验
    "rich>=13.0",             # 终端渲染
    "prompt-toolkit>=3.0",    # 终端输入
    "watchdog>=4.0",          # 文件监控
    "tenacity>=8.0",          # 重试机制
    "tomli-w>=1.0",           # TOML 写入
]
```

---

## 8. 已完成 / 进行中

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1: 骨架 + 配置 + REPL | Done | 配置向导（必填/可选分离）、TOML 读写、CLI 主循环、/ 命令补全 |
| Phase 2: 模型层 | Done | LiteLLM + httpx 双模式，流式输出，SSE 解析，缓存 token 追踪，Embedder |
| Phase 3: 工具层 — 原生工具 | Done | @tool 装饰器 + builtin/ 包（23 个工具，按功能域拆分）|
| Phase 4: 工具层 — MCP | Done | MCP Client 连接管理 |
| Phase 5: 记忆层 — 短期 + 压缩 | Done | 对话历史 + 3 种触发 + Task-based 结构化压缩 |
| Phase 6: 上下文层 | Done | 文件加载 + watchdog 热更新 + 动态工具指南注入 |
| Phase 7: 子 Agent + 向导 | Done | spawn_agent/resume_agent（工具式，并行，隔离）+ 首次运行向导 |
| Phase 8: 可观测性 | Done | Tracing + Token 消耗展示 + 本地 Web 仪表盘 + Audit Log |
| Phase 9: 长期记忆 | Done | 结构化三层（profile/fact/lesson）+ operations 增量 + Embedding 向量检索 |
| Phase 10: 插件系统 | Done | 目录扫描加载 + on_span_end/on_session_end hooks + friday-tracing 示例 |
| Phase 11: 数据管理 | Done | Trace/Session/Audit 留存策略 + 启动时后台清理 |
| Phase 12: 代码架构重构 | Done | tools/builtin/ 包拆分，skills 目录化，统一 workspace 结构，删除死代码 |
| Phase 13: 打磨 | In Progress | 补充单元测试，MCP 优雅降级 |

---

## 9. 已知问题与后续计划

- [ ] 补充单元测试覆盖（插件层、记忆层）
- [ ] MCP Server 连接失败时的优雅降级
- [ ] 长期记忆：历史条目补充向量（首次配置 Embedding 后的迁移）
