# PicoMind 架构

## 运行流程

```text
CLI
  -> 配置与工作区解析
  -> AgentLoop
     -> ContextBuilder
     -> DeepSeekProvider
     -> ToolRegistry
        -> 本地工具
        -> MCP 工具
        -> SpawnTool -> SubagentManager
     -> SessionManager
     -> MemoryConsolidator
```

CLI 负责终端渲染和用户命令。Agent Loop 负责模型迭代、工具调用与持久化。
Provider 只负责在模型 API 与 PicoMind 的 `LLMResponse` 之间转换。

## 核心边界

- `providers`：DeepSeek 协议转换、重试和流式输出。
- `agent/loop.py`：单次请求生命周期和工具迭代上限。
- `agent/context.py`：系统提示词、引导文件、记忆和技能摘要。
- `agent/tools`：工具契约、参数校验、本地执行、Web 和 MCP。
- `agent/subagent.py`：同一轮内隔离执行，并通过信号量限制并发。
- `session`：追加式 JSONL 持久化和原子替换。
- `config`：TOML 模型、加载、路径解析和工作区模板。
- `security`：由各工具共享的 SSRF 和私网防护。

## 持久化

选定的工作区包含：

```text
AGENTS.md
SOUL.md
USER.md
TOOLS.md
memory/MEMORY.md
memory/HISTORY.md
skills/<技能名>/SKILL.md
sessions/<会话键>.jsonl
```

会话写入采用原子替换。被归档的对话片段会摘要进 Markdown 长期记忆；
如果整合失败，原始片段会追加到 `HISTORY.md`。

## 工具执行

每个工具都提供 OpenAI 兼容的 JSON Schema。注册表在执行前校验必填字段和
基础类型。同一次模型响应中的独立工具调用通过 `asyncio.gather` 并发执行。
注册表还会施加每个工具自己的外层超时。超时和用户取消会继续传播到模型请求、
MCP 调用、子 Agent 和 Shell 进程树。

`spawn` 使用同一执行路径，因此多个 spawn 调用可以并行运行。每个子 Agent
都拥有独立消息历史、一个不包含 `spawn` 的工具注册表和共享的并发信号量。

## 安全

默认信任边界是选定的工作区。文件系统工具在访问前解析并验证路径。Shell
命令以工作区为当前目录，拒绝危险模式、路径穿越和私有 URL。Web 请求在
连接前解析 DNS，并拒绝私有、回环、链路本地和元数据地址。

敏感文件名由统一规则识别。文件读取、写入、编辑、目录列举以及 Shell 命令
引用都会拒绝 `.env`、私钥、credentials 文件和本地 DeepSeek Key 文件。

这是应用层边界，不是容器或操作系统级沙箱。

## 明确不做

PicoMind 当前不包含聊天渠道、Gateway、Cron、Heartbeat 或多 Provider
路由。这些能力对当前单用户 CLI 范围不是必需项，并会显著扩大生命周期和
故障处理复杂度。
