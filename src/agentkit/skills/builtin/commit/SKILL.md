---
description: 分析 git diff 并生成 commit message 提交
---

请帮我完成一次 git commit。步骤如下：

1. 先执行 `git status` 和 `git diff --staged` 查看当前变更
2. 如果没有已暂存的变更，执行 `git diff` 查看未暂存的变更，并提示用户需要先 `git add`
3. 根据变更内容生成一个简洁的 commit message（一行标题 + 可选的正文）
4. 如果用户提供了 message，直接使用该 message
5. 执行 `git commit -m "..."` 完成提交

用户参数：$ARGUMENTS
