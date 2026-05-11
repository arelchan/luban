---
description: 自查能力 — 回答关于 Luban 自身的问题（工具、命令、配置、逻辑等）
---

用户正在询问关于你自身（Luban）的问题。你必须基于客观事实回答，不要猜测或编造。

## 回答原则

1. 先调用 `introspect_info` 获取运行时状态（工具列表、Skills、命令、配置、会话信息等）
2. 如果用户问的是具体实现逻辑或使用方式，再调用 `introspect_source` 读取相关源码或文档
3. 基于读到的真实内容组织回答，不要凭记忆回答

## 常用查询路径

- 工具实现：`tools/builtin/`
- 命令和 i18n：`cli/i18n.py`、`cli/app.py`
- 记忆机制：`memory/short_term.py`、`memory/long_term.py`、`memory/manager.py`
- 编排逻辑：`orchestration/loop.py`
- 配置模型：`config/models.py`
- 会话管理：`session/store.py`
- Skills 加载：`skills/loader.py`
- 项目文档：`README.md`、`PRD.md`

## 回答格式

- 简洁准确，引用具体的文件或配置项
- 如果涉及代码，贴出关键片段
- 如果用户没有具体问题，展示功能概览（调用 `introspect_info("all")`）

用户问题：$ARGUMENTS
