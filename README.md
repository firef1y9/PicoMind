# PicoMind

PicoMind 是一个面向 Windows 的轻量级、本地优先个人 AI 助手。它参考了
[nanobot](https://github.com/HKUDS/nanobot) 的架构设计，但核心代码独立实现。

## 当前范围

- Python 3.11+ 命令行界面
- 仅接入 DeepSeek `deepseek-chat`
- 交互式流式对话和一次性任务
- JSONL 会话与 Markdown 长期记忆
- 工作区受限的文件、Shell、Web、MCP 和 Skills 工具
- 同一轮内并行运行、上下文隔离的子 Agent
- MCP 传输方式：stdio、SSE、streamable HTTP

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

设置 DeepSeek API Key：

```powershell
$env:PICOMIND_DEEPSEEK_API_KEY = "你的密钥"
```

在本机开发时，也可以从 `deepseek api.txt` 临时加载，不必把密钥写进配置：

```powershell
$env:PICOMIND_DEEPSEEK_API_KEY = (Get-Content -LiteralPath ".\deepseek api.txt" -Raw -Encoding UTF8).Trim()
```

该文件已被 Git 忽略。

## 快速开始

```powershell
picomind init
picomind doctor
picomind chat
picomind run "列出工作区文件并概括项目"
```

使用指定项目作为工作区：

```powershell
picomind --workspace D:\Projects\Example chat
```

## 命令

```text
picomind init
picomind chat
picomind run "任务"
picomind session list
picomind session resume <会话键>
picomind session clear <会话键>
picomind tools list
picomind config show
picomind doctor [--live]
```

会话内命令：

```text
/new /resume /clear /model /tools /session /stop /exit
```

任务运行期间可以输入 `/stop` 取消，也可以按 `Ctrl+C`。取消会传播到模型请求、
工具调用、子 Agent 和正在运行的 Shell 进程树。

## 配置

默认配置文件为 `~/.picomind/config.toml`，默认工作区为
`~/.picomind/workspace`。

凭据读取顺序：

1. `PICOMIND_DEEPSEEK_API_KEY`
2. `config.toml` 中的 `provider.api_key`

Web 搜索默认使用 Brave；未配置 Brave 或请求失败时回退 DuckDuckGo。
`web_fetch` 优先使用 Jina Reader，失败后回退到本地 HTML 正文提取。

Web 请求设置了强制超时，避免天气或新闻站点无响应时卡住整个对话：

```toml
[tools.web]
proxy = ""
request_timeout_seconds = 12
search_timeout_seconds = 10
jina_timeout_seconds = 5
```

DuckDuckGo 搜索运行在可强杀的独立子进程中。即使底层网络请求卡死，也不会
阻止 PicoMind 返回超时结果或正常退出。

### MCP

```toml
[tools.mcp_servers.filesystem]
type = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/Projects"]
tool_timeout = 30
enabled_tools = ["*"]

[tools.mcp_servers.remote]
type = "streamableHttp"
url = "https://example.com/mcp"
headers = { Authorization = "Bearer replace-me" }
```

MCP 工具会以 `mcp_<服务名>_<工具名>` 的形式提供给模型。

## 安全

- 文件和 Shell 工具默认限制在当前工作区。
- 所有工具调用都有外层超时；Shell 超时或取消时会终止进程树。
- `deepseek api.txt`、`.env`、`*.pem`、`*.key`、SSH 私钥和 credentials 等
  敏感文件会被文件工具与 Shell 统一拦截。
- Shell 会拦截危险模式、路径穿越和内部 URL。
- Web 请求会拒绝私有、回环、链路本地和元数据地址。
- 已完全关闭遥测；日志仅保存在本地并自动轮转。

这些保护属于应用层安全边界，不等同于操作系统级沙箱。

## 开发

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

真实 DeepSeek 测试需要显式启用：

```powershell
$env:PICOMIND_RUN_LIVE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -m live
```

运行架构见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
