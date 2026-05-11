"""Prompt templates for memory operations."""

# ─── Context Compression Prompt ─────────────────────────────────────────────

COMPRESSION_PROMPT = """\
你是一个对话压缩助手。你的任务是将一段对话历史压缩为结构化的任务摘要，在最小化 token 占用的同时保留对后续对话有价值的核心信息。

## 切分规则

将对话按用户的独立请求切分为多个 Task。切分依据：
- 用户明确提出了新的需求或问题
- 话题发生了明显转换
- 前一个任务已有明确结论，用户开始新的方向

如果一个请求包含多个步骤但服务于同一目标，应归为同一个 Task。

## 输出格式

每个 Task 按以下结构输出（根据状态选择对应模板）：

### ✓ 已完成的 Task（侧重结果和经验）

## Task N [T起-T止]: [一句话标题]
- 意图：用户想要什么
- 决策：最终采用了什么方案，关键选择是什么
- 结论：最终结果、经验教训、需要注意的事项
- 涉及：[文件路径列表]

### ⧖ 进行中的 Task（侧重思路和过程）

## Task N [T起-]: [一句话标题]
- 意图：用户想要什么
- 决策过程：考虑了哪些方案，为什么排除了 X，为什么选择了 Y
- 当前进展：已完成哪些步骤，正在做什么
- 待解决：接下来需要做什么
- 涉及：[文件路径列表]

### ✗ 未完成/已放弃的 Task（侧重原因）

## Task N [T起-T止]: [一句话标题]
- 意图：用户想要什么
- 卡点：为什么没完成（报错、方向不对、用户主动放弃）
- 如需继续：可能的方向或注意事项

## 压缩原则

1. 保留：用户意图、最终决策及理由、工具返回的关键结论、未完成任务的断点信息
2. 去掉：中间试错过程（已完成任务的）、重复确认、纯解释性内容、工具返回的原始大段文本、已被推翻的方案细节（已完成任务的）
3. 工具结果：只保留结论性摘要，不复制原始输出
4. 代码变更：只描述改了什么，不包含具体 diff
5. 长度：已完成的 Task 3-4 行，进行中的 Task 4-6 行，未完成的 2-3 行
6. 语言：与用户对话使用的语言保持一致，技术术语/文件名/命令保留原文

## 对话历史

{conversation}
"""

# ─── Long-term Memory Extraction Prompt ─────────────────────────────────────

DEFAULT_EXTRACTION_PROMPT = """\
你是一个记忆提取助手。分析对话记录，从中提取对未来对话有长期价值的信息，输出增量操作列表。

## 三种记忆类型

### profile（用户画像偏好）
关于"这个人是谁、怎么工作的"。会随时间演变，同一 category 通常只有一个有效值。
category 取值：技术栈 | 工作习惯 | 沟通偏好 | 工作背景

示例：
- "用户使用 Python 3.13，偏好 asyncio 异步风格" → category: 技术栈
- "用户在美团做 ML/AI 工程" → category: 工作背景
- "用户喜欢简洁代码，不要过度注释" → category: 工作习惯

### fact（客观事实）
关于"这个项目/环境里的确定性信息"。是客观存在的，不是偏好。
scope 取值：project | environment | global

示例：
- "内网 Anthropic 代理地址是 https://xxx/v1" → scope: environment
- "项目名称是 agentkit，是一个 CLI Agent 框架" → scope: project
- "评测 pipeline 只能用 gemini-2-flash-preview 模型" → scope: project

### lesson（经验教训）
关于"做过的事情里沉淀出来的规律和约定"。是经验性的，需要 title 概括。

示例：
- title: "修改 agentkit 代码必须同步更新文档", content: "每次修改代码后必须同步更新 README.md 和 PRD.md"
- title: "危险操作前需要用户确认", content: "执行 rm -rf、force push 等不可逆操作前必须先向用户确认"

## 操作类型

- **add**：发现了新信息，之前没有
- **update**：已有条目的内容需要更新（用 target_id 指定）
- **merge**：新信息是已有条目的补充，合并进去（用 target_id 指定）
- **skip**：和已有条目完全重复，不写入
- **delete**：已有条目的信息明确过时或错误（用 target_id 指定，reason 说明原因）

## 已有记忆条目（可能为空）

{existing_memories}

## 对话记录

{conversation_log}

## 输出格式

只输出 JSON，不要任何解释文字：

```json
{{
  "operations": [
    {{
      "action": "add",
      "type": "profile",
      "category": "技术栈",
      "content": "...",
      "evidence": "对话中提及的依据"
    }},
    {{
      "action": "add",
      "type": "fact",
      "scope": "project",
      "content": "..."
    }},
    {{
      "action": "add",
      "type": "lesson",
      "title": "...",
      "content": "...",
      "context": "为什么形成这条经验"
    }},
    {{
      "action": "update",
      "target_id": "p_abc123",
      "content": "更新后的内容"
    }},
    {{
      "action": "delete",
      "target_id": "f_old456",
      "reason": "信息已过时"
    }}
  ]
}}
```

## 提取原则

1. 只提取有长期价值的信息，不提取当次对话的具体内容（比如"用户问了什么问题"）
2. 每条内容简洁，1-2 句话
3. 不确定是否有价值的信息，宁可不提取
4. 如果对话中没有值得提取的信息，返回 {{"operations": []}}
"""
