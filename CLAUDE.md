# Luban — Claude Code 项目规则

## 核心约束（每次修改代码都必须遵守）

### 文档同步
- **每完成一个功能点，立刻同步更新 README.md 和 PRD.md**，不要攒到最后
- README.md：用户视角，关注特性列表、配置示例、命令列表、架构目录
- PRD.md：开发者视角，关注层设计、数据结构、流程、配置模型层级、已完成阶段
- **PRD 撰写原则：产品设计与实现方案必须分开**
  - 每层的「产品设计」写清楚：解决什么问题、面向谁、交互方式、功能边界、数据格式
  - 每层的「实现方案」写清楚：核心文件、类/函数、关键算法、数据流、异常处理
  - 禁止在产品设计段落里混入代码级细节（如类名、函数名、文件路径）
  - 禁止在实现方案段落里混入产品决策（如"为什么选这个方案"属于产品设计）
- 新增模块 → 更新架构图和目录结构
- 新增配置字段 → 更新 PRD 的配置模型层级 + README 的配置示例
- 新增工具 → 更新工具数量
- 新增命令 → 更新 README 命令表
- 阶段完成 → 更新 PRD 第 8 节的进度表

### 测试
- 每次改动后必须跑 `.venv/bin/python -m pytest tests/ -q`，确保全绿才算完成

### 代码规范
- 修改文件前必须先读取，禁止盲改
- 工具拆分在 `src/agentkit/tools/builtin/` 包下，按功能域分文件
- 新增工具后更新 `tools/builtin/__init__.py` 的导出
- 新增工具的中文描述加到 `cli/i18n.py` 的 `TOOL_DESCRIPTIONS`

---

## 项目结构

```
src/agentkit/
├── audit.py              # 开发者审计日志（单例）
├── cleanup.py            # 数据清理（trace/session/audit 留存）
├── config/               # Pydantic 配置模型 + TOML 读写
├── cron/                 # 定时任务调度（job/store/scheduler）
├── media/                # 多模态输入预处理（CLI 层子模块）
├── model/                # LLM client + Embedder
├── tools/
│   └── builtin/          # 内置工具包（按功能域拆分）
│       ├── context.py    # _runtime_context + set_runtime_context
│       ├── files.py      # read/write/edit/list_directory
│       ├── shell.py      # run_command
│       ├── search.py     # glob/grep
│       ├── utility.py    # get_current_time/calculate
│       ├── web.py        # web_fetch/web_search
│       ├── tasks.py      # task_create/update/get/list
│       ├── memory.py     # memory_get_profile/keyword/search
│       ├── session.py    # rename_session/introspect_*
│       └── agents.py     # spawn_agent/resume_agent
├── memory/               # 短期记忆 + 压缩 + 长期结构化记忆
├── context/              # soul/agents/memory.md 加载 + watchdog
├── orchestration/        # Agent Loop + Sub-Agent Executor
├── plugins/              # 插件系统（目录扫描 + hook 分发）
├── session/              # 多会话管理
├── skills/
│   └── builtin/<name>/SKILL.md  # 每个 skill 一个目录包
├── tracing/              # OpenTelemetry 风格 span
├── dashboard/            # 本地 Web UI
└── cli/                  # REPL + 多模态预处理 + 渲染 + 向导
```

## 工作空间结构

```
~/.agentkit/workspace/
├── soul.md
├── agents.md
├── memory.md
├── memories.json
├── skills/      # 用户自定义 Skills（目录包格式，入口 SKILL.md）
└── plugins/     # 用户插件
```

---

## 关键设计约定

### _runtime_context
- 位置：`tools/builtin/context.py`
- 用途：工具函数访问运行时组件的全局注入桥
- 注入时机：`app.py` 初始化完成后调用 `set_runtime_context()`
- 任何工具需要访问运行时对象，从这里取，不直接 import

### 插件
- 插件目录：`~/.agentkit/workspace/plugins/<name>/`
- 插件日志：重定向到 `~/.agentkit/plugins.log`，绝不写 stderr（会污染 prompt_toolkit 终端）
- 插件 hook 内的异常必须被捕获，不能传播到主流程

### Audit Log
- 每个关键操作都要埋点：`from agentkit.audit import audit; audit(component, action, ...)`
- 新增模块时，在模块的关键路径上埋 start/done/error 三个事件

### Skills
- **统一格式**：一个 skill = 一个目录，入口固定 `SKILL.md`
- 内置：`src/agentkit/skills/builtin/<name>/SKILL.md`
- 用户：`~/.agentkit/workspace/skills/<name>/SKILL.md`
- `SKILL.md` 格式：YAML frontmatter（name, description）+ prompt body，`$ARGUMENTS` 占位符
- 目录内可放 `references/`、`scripts/` 等附属文件，不会被当 skill 加载
- loader 只扫描含 `SKILL.md` 的子目录，忽略隐藏目录和无入口的目录

### 搜索引擎
- 优先 Brave Search API（有 key 时），fallback Bing HTML 爬取
- 配置：`config.toml [tools.web_search]`

### 长期记忆
- 必须配置 Embedding 才启用（`memory.embedding.enabled = true`）
- 三种类型：profile / fact / lesson
- 存储：`~/.agentkit/workspace/memories.json`（JSONL）

### 向导（wizard.py）
- 必填步骤：模型供应商 + API Key（未完成每次启动都触发）
- 可选步骤（跳过后写入 `cli.skipped_optional_setup`，不再弹）：搜索引擎、Embedding
