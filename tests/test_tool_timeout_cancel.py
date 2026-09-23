import asyncio
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from picomind.agent.loop import AgentLoop
from picomind.agent.tools.base import Tool
from picomind.agent.tools.registry import ToolRegistry
from picomind.agent.tools.shell import ExecTool
from picomind.cli import _run_agent_with_control
from picomind.config.schema import Config
from picomind.providers.base import GenerationSettings, LLMResponse


class SlowTool(Tool):
    timeout_seconds = 0.05

    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "slow tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **_: Any) -> str:
        await asyncio.sleep(1)
        return "late"


class BlockingTool(Tool):
    timeout_seconds = None

    def __init__(self) -> None:
        self.started = asyncio.Event()

    @property
    def name(self) -> str:
        return "blocking"

    @property
    def description(self) -> str:
        return "blocking tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **_: Any) -> str:
        self.started.set()
        await asyncio.Event().wait()
        return "never"


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.generation = GenerationSettings()
        self.default_model = "deepseek-chat"

    async def chat_with_retry(self, **_: Any) -> LLMResponse:
        self.started.set()
        await asyncio.Event().wait()
        return LLMResponse(content="never")


class StopPrompt:
    async def prompt_async(self, message: str) -> str:
        return "/stop"


@pytest.mark.asyncio
async def test_registry_enforces_tool_timeout() -> None:
    registry = ToolRegistry()
    registry.register(SlowTool())

    result = await registry.execute("slow", {})

    assert "执行超时" in result


@pytest.mark.asyncio
async def test_registry_propagates_cancellation() -> None:
    tool = BlockingTool()
    registry = ToolRegistry()
    registry.register(tool)
    task = asyncio.create_task(registry.execute("blocking", {}))
    await tool.started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_agent_cancel_active_request(tmp_path: Path) -> None:
    provider = BlockingProvider()
    config = Config()
    config.agent.defaults.workspace = str(tmp_path)
    agent = AgentLoop(config, provider, tmp_path)
    task = asyncio.create_task(agent.process("wait", session_key="cli:test"))
    await provider.started.wait()

    assert agent.cancel_active() == 1
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent.has_active_request is False


@pytest.mark.asyncio
async def test_interactive_stop_cancels_request(tmp_path: Path) -> None:
    provider = BlockingProvider()
    config = Config()
    config.agent.defaults.workspace = str(tmp_path)
    agent = AgentLoop(config, provider, tmp_path)

    async def ignore(*_: Any, **__: Any) -> None:
        return None

    result = await _run_agent_with_control(
        agent,
        "wait",
        session_key="cli:test",
        on_delta=None,
        on_progress=ignore,
        prompt=StopPrompt(),  # type: ignore[arg-type]
    )

    assert result is None


@pytest.mark.asyncio
async def test_shell_cancellation_stops_child_process(tmp_path: Path) -> None:
    script = tmp_path / "delayed_write.py"
    marker = tmp_path / "marker.txt"
    script.write_text(
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(1.5)\n"
        f"Path({str(marker)!r}).write_text('survived', encoding='utf-8')\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        command = subprocess.list2cmdline(["python", str(script)])
    else:
        command = shlex.join(["python", str(script)])
    tool = ExecTool(tmp_path, timeout=10)
    task = asyncio.create_task(tool.execute(command=command))
    await asyncio.sleep(0.2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1.7)

    assert not marker.exists()
