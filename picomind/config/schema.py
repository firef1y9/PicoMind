"""Pydantic configuration models for PicoMind."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Base model with predictable field handling."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AgentDefaults(Base):
    workspace: str = "~/.picomind/workspace"
    model: str = "deepseek-chat"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    max_subagent_iterations: int = 15
    max_concurrent_subagents: int = 3


class AgentConfig(Base):
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"

    @property
    def resolved_api_key(self) -> str:
        return os.getenv("PICOMIND_DEEPSEEK_API_KEY", "").strip() or self.api_key.strip()


class ExecConfig(Base):
    enabled: bool = True
    timeout: int = 60
    max_output_chars: int = 10_000
    path_append: str = ""


class WebSearchConfig(Base):
    provider: Literal["brave", "tavily", "duckduckgo", "searxng", "jina"] = "brave"
    api_key: str = ""
    base_url: str = ""
    max_results: int = 5
    fallback_to_duckduckgo: bool = True

    @property
    def resolved_api_key(self) -> str:
        env_names = {
            "brave": "BRAVE_API_KEY",
            "tavily": "TAVILY_API_KEY",
            "jina": "JINA_API_KEY",
        }
        if self.provider == "searxng":
            return os.getenv("SEARXNG_BASE_URL", "").strip() or self.base_url.strip()
        env_key = env_names.get(self.provider, "")
        return (os.getenv(env_key, "").strip() if env_key else "") or self.api_key.strip()


class WebConfig(Base):
    proxy: str = ""
    request_timeout_seconds: float = 12.0
    search_timeout_seconds: float = 10.0
    jina_timeout_seconds: float = 5.0
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class SecurityConfig(Base):
    restrict_to_workspace: bool = True


class MCPServerConfig(Base):
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tool_timeout: int = 30
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])


class ToolsConfig(Base):
    exec: ExecConfig = Field(default_factory=ExecConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class LoggingConfig(Base):
    level: str = "INFO"
    retention: int = 7


class Config(Base):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @property
    def workspace_path(self) -> Path:
        return Path(self.agent.defaults.workspace).expanduser()
