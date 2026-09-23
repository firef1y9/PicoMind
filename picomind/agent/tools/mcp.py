"""MCP client integration for stdio, SSE, and streamable HTTP servers."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from picomind.agent.tools.base import Tool
from picomind.agent.tools.registry import ToolRegistry
from picomind.config.schema import MCPServerConfig


def _normalize_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    normalized = dict(schema)
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
    if "properties" in normalized and isinstance(normalized["properties"], dict):
        normalized["properties"] = {
            key: _normalize_schema(value) if isinstance(value, dict) else value
            for key, value in normalized["properties"].items()
        }
    return normalized


class MCPToolWrapper(Tool):
    def __init__(
        self,
        session: Any,
        server_name: str,
        tool_def: Any,
        timeout: int,
    ) -> None:
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        self._parameters = _normalize_schema(
            tool_def.inputSchema or {"type": "object", "properties": {}}
        )
        self._timeout = timeout
        self.timeout_seconds = float(timeout) + 2.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return f"Error: MCP 工具执行超过 {self._timeout} 秒"
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task and task.cancelling():
                raise
            return "Error: MCP 工具调用已取消"
        except Exception as exc:
            return f"Error: MCP 工具调用失败：{type(exc).__name__}: {exc}"
        parts: list[str] = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "（无输出）"


def _transport(config: MCPServerConfig) -> str:
    if config.type:
        return config.type
    if config.command:
        return "stdio"
    if config.url.rstrip("/").endswith("/sse"):
        return "sse"
    return "streamableHttp"


async def connect_mcp_servers(
    servers: dict[str, MCPServerConfig],
    registry: ToolRegistry,
    stack: AsyncExitStack,
) -> None:
    if not servers:
        return
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    for name, config in servers.items():
        try:
            transport = _transport(config)
            if transport == "stdio":
                if not config.command:
                    logger.warning("MCP server '{}' has no command", name)
                    continue
                params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env or None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport == "sse":
                if not config.url:
                    logger.warning("MCP server '{}' has no URL", name)
                    continue

                def factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    return httpx.AsyncClient(
                        headers={**config.headers, **(headers or {})} or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                read, write = await stack.enter_async_context(
                    sse_client(config.url, httpx_client_factory=factory)
                )
            elif transport == "streamableHttp":
                if not config.url:
                    logger.warning("MCP server '{}' has no URL", name)
                    continue
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=config.headers or None,
                        follow_redirects=True,
                        timeout=None,
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(config.url, http_client=client)
                )
            else:
                logger.warning("MCP server '{}' uses unknown transport '{}'", name, transport)
                continue

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            discovered = await session.list_tools()
            enabled = set(config.enabled_tools)
            allow_all = "*" in enabled
            registered = 0
            for tool_def in discovered.tools:
                wrapped = f"mcp_{name}_{tool_def.name}"
                if not allow_all and tool_def.name not in enabled and wrapped not in enabled:
                    continue
                registry.register(
                    MCPToolWrapper(
                        session,
                        name,
                        tool_def,
                        timeout=config.tool_timeout,
                    )
                )
                registered += 1
            logger.info("MCP server '{}' registered {} tools", name, registered)
        except Exception:
            logger.exception("Failed to connect MCP server '{}'", name)
