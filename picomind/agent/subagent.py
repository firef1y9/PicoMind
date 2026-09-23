"""Same-turn, isolated subagent execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from picomind.agent.tools.registry import ToolRegistry
from picomind.providers.base import LLMProvider


class SubagentManager:
    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        workspace: Path,
        registry_factory: Callable[[], ToolRegistry],
        max_iterations: int = 15,
        max_concurrency: int = 3,
    ) -> None:
        self.provider = provider
        self.model = model
        self.workspace = workspace
        self.registry_factory = registry_factory
        self.max_iterations = max_iterations
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run(self, task: str, label: str | None = None) -> str:
        async with self._semaphore:
            tools = self.registry_factory().subset({"spawn", "message"})
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "你是 PicoMind 的专注子 Agent。只完成分配给你的任务，不能再派生"
                        "新的子 Agent。返回简洁、可直接供父 Agent 使用的结果。\n\n"
                        f"工作区：{self.workspace}"
                    ),
                },
                {"role": "user", "content": task},
            ]
            final: str | None = None
            for _ in range(self.max_iterations):
                response = await self.provider.chat_with_retry(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                )
                if response.finish_reason == "error":
                    return response.content or "Error: 子 Agent 调用模型失败"
                if not response.has_tool_calls:
                    final = response.content
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            call.to_openai_tool_call() for call in response.tool_calls
                        ],
                    }
                )
                calls = [(call.name, call.arguments) for call in response.tool_calls]
                results = await tools.execute_many(calls)
                for call, result in zip(response.tool_calls, results, strict=False):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": str(result),
                        }
                    )
            return final or "子 Agent 达到迭代上限，未生成最终结果。"
