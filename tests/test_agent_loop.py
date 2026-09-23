import asyncio
from pathlib import Path
from typing import Any

import pytest

from picomind.agent.loop import AgentLoop
from picomind.agent.subagent import SubagentManager
from picomind.agent.tools.registry import ToolRegistry
from picomind.config.schema import Config
from picomind.providers.base import GenerationSettings, LLMResponse, ToolCallRequest


class FakeProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.generation = GenerationSettings()
        self.default_model = "deepseek-chat"

    async def chat_with_retry(self, **_: Any) -> LLMResponse:
        return self.responses.pop(0)

    async def chat_stream_with_retry(self, **kwargs: Any) -> LLMResponse:
        response = self.responses.pop(0)
        callback = kwargs.get("on_content_delta")
        if callback and response.content:
            await callback(response.content)
        return response


class ConcurrentProvider:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.generation = GenerationSettings()
        self.default_model = "deepseek-chat"

    async def chat_with_retry(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        return LLMResponse(content=str(messages[-1]["content"]), finish_reason="stop")


@pytest.mark.asyncio
async def test_agent_executes_tool_and_saves_session(tmp_path: Path) -> None:
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call-1",
                    name="write_file",
                    arguments={"path": "hello.txt", "content": "hello"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    provider = FakeProvider(responses)
    config = Config()
    config.agent.defaults.workspace = str(tmp_path)
    agent = AgentLoop(config, provider, tmp_path)

    result = await agent.process("write a file", session_key="cli:test")
    await agent.close()

    assert result == "done"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    history = agent.sessions.get_or_create("cli:test").messages
    assert history[0]["role"] == "user"
    assert any(message["role"] == "tool" for message in history)


@pytest.mark.asyncio
async def test_subagents_run_parallel_with_concurrency_limit(tmp_path: Path) -> None:
    provider = ConcurrentProvider()
    manager = SubagentManager(
        provider=provider,
        model="deepseek-chat",
        workspace=tmp_path,
        registry_factory=ToolRegistry,
        max_concurrency=2,
    )

    results = await asyncio.gather(
        manager.run("one"),
        manager.run("two"),
        manager.run("three"),
    )

    assert results == ["one", "two", "three"]
    assert provider.max_active == 2
