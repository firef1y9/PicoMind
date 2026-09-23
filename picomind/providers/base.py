"""Provider interfaces and shared response models."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai_tool_call(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.1
    max_tokens: int = 8192


class LLMProvider(ABC):
    """Abstract interface used by the agent loop and memory consolidator."""

    _RETRY_DELAYS = (1, 2, 4)
    _TRANSIENT_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
    )

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.generation = GenerationSettings()

    @staticmethod
    def _clean_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
        cleaned: list[dict[str, Any]] = []
        for message in messages:
            item = {key: value for key, value in message.items() if key in allowed}
            if item.get("role") == "assistant" and "content" not in item:
                item["content"] = None
            if isinstance(item.get("content"), str) and not item["content"]:
                item["content"] = None if item.get("tool_calls") else "(empty)"
            cleaned.append(item)
        return cleaned

    @classmethod
    def _is_transient(cls, content: str | None) -> bool:
        text = (content or "").lower()
        return any(marker in text for marker in cls._TRANSIENT_MARKERS)

    async def _safe_chat(self, **kwargs: Any) -> LLMResponse:
        try:
            return await self.chat(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(content=f"Error: 调用大模型失败：{exc}", finish_reason="error")

    async def _safe_stream(self, **kwargs: Any) -> LLMResponse:
        try:
            return await self.chat_stream(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(content=f"Error: 调用大模型失败：{exc}", finish_reason="error")

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs = {
            "messages": messages,
            "tools": tools,
            "model": model,
            "max_tokens": max_tokens if max_tokens is not None else self.generation.max_tokens,
            "temperature": (
                temperature if temperature is not None else self.generation.temperature
            ),
            "tool_choice": tool_choice,
        }
        return await self._retry(lambda: self._safe_chat(**kwargs))

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        kwargs = {
            "messages": messages,
            "tools": tools,
            "model": model,
            "max_tokens": max_tokens if max_tokens is not None else self.generation.max_tokens,
            "temperature": (
                temperature if temperature is not None else self.generation.temperature
            ),
            "tool_choice": tool_choice,
            "on_content_delta": on_content_delta,
        }
        return await self._retry(lambda: self._safe_stream(**kwargs))

    async def _retry(self, call: Callable[[], Awaitable[LLMResponse]]) -> LLMResponse:
        response = await call()
        for attempt, delay in enumerate(self._RETRY_DELAYS, start=1):
            if response.finish_reason != "error" or not self._is_transient(response.content):
                return response
            logger.warning(
                "Transient DeepSeek error (attempt {}/{}), retrying in {}s",
                attempt,
                len(self._RETRY_DELAYS),
                delay,
            )
            await asyncio.sleep(delay)
            response = await call()
        return response

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def get_default_model(self) -> str:
        raise NotImplementedError
