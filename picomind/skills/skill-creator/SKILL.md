---
name: skill-creator
description: 在工作区中创建或更新可复用的 PicoMind 技能。
---

# 技能创建器

每个技能都创建在 `skills/<技能名>/SKILL.md`。

必需的 frontmatter：

```yaml
---
name: skill-name
description: 用一句话说明什么时候使用该技能。
---
```

正文应聚焦于可重复执行的工作流，只保留能够改变 Agent 行为的指令。大型参考资料放在
技能目录内的独立文件中，并从 `SKILL.md` 链接过去。
