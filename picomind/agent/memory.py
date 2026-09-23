"""Markdown long-term memory and optional LLM consolidation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from picomind.config.paths import ensure_dir
from picomind.providers.base import LLMProvider
from picomind.session.manager import Session

_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存简洁的历史摘要并更新长期记忆。",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {"type": "string"},
                    "memory_update": {"type": "string"},
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    def __init__(self, workspace: Path) -> None:
        directory = ensure_dir(workspace / "memory")
        self.memory_file = directory / "MEMORY.md"
        self.history_file = directory / "HISTORY.md"
        if not self.memory_file.exists():
            self.memory_file.write_text("# Long-term Memory\n", encoding="utf-8")
        if not self.history_file.exists():
            self.history_file.write_text("# History\n", encoding="utf-8")

    def read(self) -> str:
        return self.memory_file.read_text(encoding="utf-8")

    def context(self) -> str:
        content = self.read().removeprefix("# Long-term Memory").strip()
        return f"# Long-term Memory\n\n{content}" if content else ""

    def append_history(self, entry: str) -> None:
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(entry.rstrip() + "\n\n")

    def replace(self, content: str) -> None:
        self.memory_file.write_text(content.rstrip() + "\n", encoding="utf-8")


class MemoryConsolidator:
    """Consolidate old turns when the prompt approaches the configured budget."""

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        context_window_tokens: int,
        max_tokens: int,
    ) -> None:
        self.store = MemoryStore(workspace)
        self.provider = provider
        self.model = model
        self.context_window_tokens = context_window_tokens
        self.max_tokens = max_tokens

    @staticmethod
    def _estimate(messages: list[dict]) -> int:
        chars = sum(len(json.dumps(message, ensure_ascii=False)) for message in messages)
        return max(1, chars // 4)

    async def maybe_consolidate(self, session: Session) -> None:
        budget = max(4096, self.context_window_tokens - self.max_tokens - 1024)
        history = session.get_history()
        if self._estimate(history) < budget:
            return
        target = budget // 2
        end = session.last_consolidated
        removed = 0
        for index in range(session.last_consolidated, len(session.messages)):
            removed += self._estimate([session.messages[index]])
            if index > session.last_consolidated and session.messages[index].get("role") == "user":
                if removed >= max(1, self._estimate(history) - target):
                    end = index
                    break
        if end <= session.last_consolidated:
            return
        chunk = session.messages[session.last_consolidated:end]
        if await self._consolidate(chunk):
            session.last_consolidated = end

    async def _consolidate(self, messages: list[dict]) -> bool:
        if not messages:
            return True
        transcript = "\n\n".join(
            f"{item.get('role', '?')}: {item.get('content', '')}" for item in messages
        )
        prompt = (
            "根据以下对话片段更新长期记忆。调用 save_memory，提供带时间戳的历史记录，"
            "以及完整的更新后 Markdown 长期记忆。\n\n"
            f"当前记忆：\n{self.store.read()}\n\n对话内容：\n{transcript}"
        )
        response = await self.provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "你是 PicoMind 的记忆整合组件，必须准确、克制，不能编造事实。",
                },
                {"role": "user", "content": prompt},
            ],
            tools=_SAVE_MEMORY_TOOL,
            model=self.model,
            tool_choice={
                "type": "function",
                "function": {"name": "save_memory"},
            },
        )
        if response.finish_reason == "error" or not response.tool_calls:
            logger.warning("Memory consolidation failed; archiving raw messages")
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.store.append_history(f"[{stamp}] [RAW]\n{transcript}")
            return True
        args = response.tool_calls[0].arguments
        history_entry = str(args.get("history_entry") or "").strip()
        memory_update = str(args.get("memory_update") or "").strip()
        if history_entry:
            self.store.append_history(history_entry)
        if memory_update:
            self.store.replace(memory_update)
        return True
