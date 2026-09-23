"""DeepSeek adapter using the OpenAI-compatible API."""

from __future__ import annotations

import json
import secrets
import string
from collections.abc import Awaitable, Callable
from typing import Any

from json_repair import loads as repair_json
from openai import AsyncOpenAI

from picomind.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_ID_CHARS = string.ascii_letters + string.digits


def _short_id() -> str:
    return "tc_" + "".join(secrets.choice(_ID_CHARS) for _ in range(12))


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        parsed = repair_json(str(raw))
    return parsed if isinstance(parsed, dict) else {}


class DeepSeekProvider(LLMProvider):
    """DeepSeek implementation for ``deepseek-chat`` and compatible model names."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "deepseek-chat",
    ):
        super().__init__(api_key=api_key, base_url=base_url)
        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key or "missing-key",
            base_url=(base_url or "https://api.deepseek.com").rstrip("/"),
            timeout=120.0,
            max_retries=0,
        )

    def get_default_model(self) -> str:
        return self.default_model

    def _request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._clean_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        return payload

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = _get(response, "usage")
        if not usage:
            return {}
        return {
            "prompt_tokens": int(_get(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(_get(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(_get(usage, "total_tokens", 0) or 0),
        }

    @classmethod
    def _parse_response(cls, response: Any) -> LLMResponse:
        choice = (_get(response, "choices", []) or [None])[0]
        if not choice:
            return LLMResponse(content=None, finish_reason="stop")
        message = _get(choice, "message")
        tool_calls: list[ToolCallRequest] = []
        for call in _get(message, "tool_calls", []) or []:
            function = _get(call, "function")
            tool_calls.append(
                ToolCallRequest(
                    id=str(_get(call, "id") or _short_id()),
                    name=str(_get(function, "name") or ""),
                    arguments=_parse_arguments(_get(function, "arguments")),
                )
            )
        return LLMResponse(
            content=_get(message, "content"),
            tool_calls=tool_calls,
            finish_reason=str(_get(choice, "finish_reason") or "stop"),
            usage=cls._usage(response),
            reasoning_content=_get(message, "reasoning_content"),
        )

    @classmethod
    def _parse_stream(cls, chunks: list[Any]) -> LLMResponse:
        content: list[str] = []
        reasoning: list[str] = []
        tool_buffers: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def accumulate_tool(call: Any, fallback_index: int) -> None:
            index = _get(call, "index", fallback_index)
            index = fallback_index if index is None else int(index)
            buffer = tool_buffers.setdefault(
                index,
                {"id": "", "name": "", "arguments": ""},
            )
            call_id = _get(call, "id")
            if call_id:
                buffer["id"] = str(call_id)
            function = _get(call, "function")
            name = _get(function, "name")
            if name:
                buffer["name"] = str(name)
            arguments = _get(function, "arguments")
            if arguments:
                buffer["arguments"] += str(arguments)

        for chunk in chunks:
            current_usage = cls._usage(chunk)
            if current_usage:
                usage = current_usage
            choices = _get(chunk, "choices", []) or []
            if not choices:
                continue
            choice = choices[0]
            if _get(choice, "finish_reason"):
                finish_reason = str(_get(choice, "finish_reason"))
            delta = _get(choice, "delta")
            text = _get(delta, "content")
            if text:
                content.append(str(text))
            thinking = _get(delta, "reasoning_content") or _get(delta, "reasoning")
            if isinstance(thinking, str) and thinking:
                reasoning.append(thinking)
            for index, call in enumerate(_get(delta, "tool_calls", []) or []):
                accumulate_tool(call, index)

        tool_calls = [
            ToolCallRequest(
                id=buffer["id"] or _short_id(),
                name=buffer["name"],
                arguments=_parse_arguments(buffer["arguments"]),
            )
            for buffer in tool_buffers.values()
        ]
        return LLMResponse(
            content="".join(content) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning) or None,
        )

    @staticmethod
    def _error(exc: Exception) -> LLMResponse:
        body = getattr(exc, "doc", None)
        if not body:
            response = getattr(exc, "response", None)
            body = getattr(response, "text", None)
        detail = str(body).strip()[:500] if body else str(exc)
        return LLMResponse(content=f"Error: 调用 DeepSeek 失败：{detail}", finish_reason="error")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload = self._request(
            messages, tools, model, max_tokens, temperature, tool_choice
        )
        try:
            response = await self._client.chat.completions.create(**payload)
            return self._parse_response(response)
        except Exception as exc:
            return self._error(exc)

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
        payload = self._request(
            messages, tools, model, max_tokens, temperature, tool_choice
        )
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        try:
            stream = await self._client.chat.completions.create(**payload)
            chunks: list[Any] = []
            async for chunk in stream:
                chunks.append(chunk)
                choices = _get(chunk, "choices", []) or []
                if on_content_delta and choices:
                    delta = _get(choices[0], "delta")
                    text = _get(delta, "content")
                    if text:
                        await on_content_delta(str(text))
            return self._parse_stream(chunks)
        except Exception as exc:
            return self._error(exc)
