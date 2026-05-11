---
description: 搜索和发现 OpenClaw skills，查找可用的技能扩展
---

帮我搜索和发现可用的 OpenClaw skills。

## 搜索来源（按优先级）

### 1. ClawHub（主要来源）
```bash
# 搜索 skills
npx clawhub search "keyword"

# 浏览分类
npx clawhub browse
```

### 2. OpenClaw Directory
- 网站：https://www.openclawdirectory.dev/skills
- 可按分类、热度或关键词搜索

### 3. GitHub
- 搜索关键词：`openclaw skill` 或 `agent-skill`
- 查找包含 `SKILL.md` 文件的仓库

## 搜索策略

- **按功能搜索**：`npx clawhub search "web search"` / `npx clawhub search "weather"`
- **按提供者搜索**：`npx clawhub search "tavily"` / `npx clawhub search "github"`
- **按热度排序**：`npx clawhub search --sort installs` / `npx clawhub search --sort stars`

## 常见 Skill 分类

| 分类 | 示例 |
|------|------|
| 核心工具 | weather, skill-creator, healthcheck |
| 集成类 | github, feishu, notion |
| 搜索类 | tavily-search, web-search-plus |
| Agent 类 | proactive-agent, coding-agent |

## 安装提示

找到合适的 skill 后：
1. 检查 skill 的依赖要求
2. 使用 `clawhub install <skill-name>` 安装
3. 安装后测试功能是否正常

## 任务

请根据用户提供的关键词搜索合适的 skills，列出搜索结果并给出推荐。如果用户未提供关键词，则展示热门 skills 分类供选择。

用户参数：$ARGUMENTS
