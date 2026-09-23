"""Tool for same-turn parallel subagent work."""

from __future__ import annotations

from typing import Any

from picomind.agent.subagent import SubagentManager
from picomind.agent.tools.base import Tool


class SpawnTool(Tool):
    timeout_seconds = 900.0

    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "在同一轮模型响应中并行运行一个专注子 Agent。子 Agent 拥有隔离上下文，"
            "不能再派生 Agent，并会直接返回结果。适合拆分为相互独立的任务。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **_: Any) -> str:
        result = await self.manager.run(task, label)
        heading = f"[{label or 'subagent'}]"
        return f"{heading}\n{result}"
