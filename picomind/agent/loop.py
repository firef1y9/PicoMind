"""Core PicoMind agent loop."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from loguru import logger

from picomind.agent.context import ContextBuilder
from picomind.agent.memory import MemoryConsolidator
from picomind.agent.skills import BUILTIN_SKILLS_DIR
from picomind.agent.subagent import SubagentManager
from picomind.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from picomind.agent.tools.mcp import connect_mcp_servers
from picomind.agent.tools.registry import ToolRegistry
from picomind.agent.tools.shell import ExecTool
from picomind.agent.tools.spawn import SpawnTool
from picomind.agent.tools.web import WebFetchTool, WebSearchTool
from picomind.config.schema import Config
from picomind.providers.base import LLMProvider
from picomind.session.manager import SessionManager

DeltaCallback = Callable[[str], Awaitable[None]]
ProgressCallback = Callable[[str], Awaitable[None]]


class AgentLoop:
    def __init__(
        self,
        config: Config,
        provider: LLMProvider,
        workspace: Path,
        *,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.workspace = workspace.resolve()
        self.config_path = config_path
        self.model = config.agent.defaults.model
        self.context = ContextBuilder(self.workspace)
        self.sessions = SessionManager(self.workspace)
        self.tools = ToolRegistry()
        self._mcp_stack: AsyncExitStack | None = None
        self._started = False
        self._active_requests: set[asyncio.Task[Any]] = set()
        self.memory = MemoryConsolidator(
            workspace=self.workspace,
            provider=provider,
            model=self.model,
            context_window_tokens=config.agent.defaults.context_window_tokens,
            max_tokens=config.agent.defaults.max_tokens,
        )
        self.subagents = SubagentManager(
            provider=provider,
            model=self.model,
            workspace=self.workspace,
            registry_factory=lambda: self.tools,
            max_iterations=config.agent.defaults.max_subagent_iterations,
            max_concurrency=config.agent.defaults.max_concurrent_subagents,
        )
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        restrict = self.config.security.restrict_to_workspace
        read_only_roots = [BUILTIN_SKILLS_DIR]
        self.tools.register(
            ReadFileTool(
                self.workspace,
                restrict_to_workspace=restrict,
                read_only_roots=read_only_roots,
            )
        )
        for tool_type in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(
                tool_type(self.workspace, restrict_to_workspace=restrict)
            )
        if self.config.tools.exec.enabled:
            self.tools.register(
                ExecTool(
                    workspace=self.workspace,
                    timeout=self.config.tools.exec.timeout,
                    max_output_chars=self.config.tools.exec.max_output_chars,
                    restrict_to_workspace=restrict,
                    path_append=self.config.tools.exec.path_append,
                )
            )
        self.tools.register(WebSearchTool(self.config.tools.web))
        self.tools.register(WebFetchTool(self.config.tools.web))
        self.tools.register(SpawnTool(self.subagents))

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self.config.tools.mcp_servers:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(
                self.config.tools.mcp_servers,
                self.tools,
                self._mcp_stack,
            )

    async def close(self) -> None:
        if self._mcp_stack:
            await self._mcp_stack.aclose()
            self._mcp_stack = None
        self._started = False

    async def process(
        self,
        content: str,
        session_key: str = "cli:default",
        *,
        on_delta: DeltaCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        current = asyncio.current_task()
        if current is not None:
            self._active_requests.add(current)
        try:
            return await self._process(
                content,
                session_key=session_key,
                on_delta=on_delta,
                on_progress=on_progress,
            )
        finally:
            if current is not None:
                self._active_requests.discard(current)

    async def _process(
        self,
        content: str,
        session_key: str,
        *,
        on_delta: DeltaCallback | None,
        on_progress: ProgressCallback | None,
    ) -> str:
        await self.start()
        session = self.sessions.get_or_create(session_key)
        await self.memory.maybe_consolidate(session)
        history = session.get_history()
        user_message = {"role": "user", "content": content}
        session.add_message(user_message)
        messages = self.context.build_messages(history, content)
        generated_start = len(messages)
        final = await self._run(
            messages,
            on_delta=on_delta,
            on_progress=on_progress,
        )
        for message in messages[generated_start:]:
            session.add_message(message)
        self.sessions.save(session)
        return final

    def cancel_active(self) -> int:
        """Cancel all active model/tool requests and return the task count."""

        tasks = [task for task in self._active_requests if not task.done()]
        for task in tasks:
            task.cancel()
        return len(tasks)

    @property
    def has_active_request(self) -> bool:
        return any(not task.done() for task in self._active_requests)

    async def _run(
        self,
        messages: list[dict[str, Any]],
        *,
        on_delta: DeltaCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        for iteration in range(1, self.config.agent.defaults.max_tool_iterations + 1):
            if on_delta:
                response = await self.provider.chat_stream_with_retry(
                    messages=messages,
                    tools=self.tools.get_definitions(),
                    model=self.model,
                    on_content_delta=on_delta,
                )
            else:
                response = await self.provider.chat_with_retry(
                    messages=messages,
                    tools=self.tools.get_definitions(),
                    model=self.model,
                )
            if response.finish_reason == "error":
                return response.content or "DeepSeek request failed."
            if not response.has_tool_calls:
                final = response.content or ""
                messages.append({"role": "assistant", "content": final})
                return final

            if on_progress:
                summary = ", ".join(
                    f"{call.name}({json.dumps(call.arguments, ensure_ascii=False)[:60]})"
                    for call in response.tool_calls
                )
                await on_progress(summary)
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
            logger.info("Executing tools: {}", ", ".join(name for name, _ in calls))
            results = await self.tools.execute_many(calls)
            for call, result in zip(response.tool_calls, results, strict=False):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": str(result),
                    }
                )
        return (
            f"Reached the maximum tool iteration limit "
            f"({self.config.agent.defaults.max_tool_iterations})."
        )
