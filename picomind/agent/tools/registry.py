"""Dynamic tool registry."""

from __future__ import annotations

import asyncio
from typing import Any

from picomind.agent.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def subset(self, exclude: set[str] | None = None) -> "ToolRegistry":
        excluded = exclude or set()
        registry = ToolRegistry()
        for name, tool in self._tools.items():
            if name not in excluded:
                registry.register(tool)
        return registry

    def get_definitions(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self.names)
            return f"Error: 未知工具“{name}”。可用工具：{available}"
        try:
            cast = tool.cast_params(params)
            errors = tool.validate_params(cast)
            if errors:
                return f"Error: 工具 {name} 的参数无效：{'; '.join(errors)}"
            timeout = tool.timeout_for(cast)
            if timeout is not None and timeout > 0:
                async with asyncio.timeout(timeout):
                    return await tool.execute(**cast)
            return await tool.execute(**cast)
        except TimeoutError:
            timeout = tool.timeout_for(cast)
            limit = f"{timeout:g} 秒" if timeout is not None else "未知时限"
            return f"Error: 工具 {name} 执行超时（{limit}）"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return f"执行工具 {name} 失败：{type(exc).__name__}: {exc}"

    async def execute_many(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> list[Any]:
        return await asyncio.gather(
            *(self.execute(name, params) for name, params in calls),
            return_exceptions=True,
        )

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
