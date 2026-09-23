"""Append-only JSONL session storage."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from picomind.config.paths import ensure_dir


def _safe_key(key: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in key)
    return safe[:120] or "default"


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_consolidated: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 0) -> list[dict[str, Any]]:
        messages = self.messages[self.last_consolidated :]
        if max_messages > 0:
            messages = messages[-max_messages:]
        while messages and messages[0].get("role") != "user":
            messages = messages[1:]
        result: list[dict[str, Any]] = []
        for message in messages:
            clean = {
                "role": message.get("role"),
                "content": message.get("content", ""),
            }
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in message:
                    clean[key] = message[key]
            result.append(clean)
        return result

    def clear(self) -> None:
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.directory = ensure_dir(self.workspace / "sessions")
        self._cache: dict[str, Session] = {}

    def path_for(self, key: str) -> Path:
        return self.directory / f"{_safe_key(key)}.jsonl"

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        session = self._load(key) or Session(key=key)
        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        messages: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        created_at = datetime.now()
        last_consolidated = 0
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("_type") == "metadata":
                    metadata = entry.get("metadata") or {}
                    created_at = datetime.fromisoformat(entry["created_at"])
                    last_consolidated = int(entry.get("last_consolidated", 0))
                else:
                    messages.append(entry)
        except Exception:
            return None
        return Session(
            key=key,
            messages=messages,
            created_at=created_at,
            updated_at=datetime.now(),
            last_consolidated=last_consolidated,
            metadata=metadata,
        )

    def save(self, session: Session) -> None:
        path = self.path_for(session.key)
        temp = path.with_suffix(".jsonl.tmp")
        metadata = {
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "last_consolidated": session.last_consolidated,
            "metadata": session.metadata,
        }
        lines = [json.dumps(metadata, ensure_ascii=False)]
        lines.extend(json.dumps(message, ensure_ascii=False) for message in session.messages)
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temp, path)
        self._cache[session.key] = session

    def clear(self, key: str) -> Session:
        session = self.get_or_create(key)
        session.clear()
        self.save(session)
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                first = path.read_text(encoding="utf-8").splitlines()[0]
                entry = json.loads(first)
            except Exception:
                continue
            if entry.get("_type") != "metadata":
                continue
            result.append(
                {
                    "key": entry.get("key", path.stem),
                    "created_at": entry.get("created_at", ""),
                    "updated_at": entry.get("updated_at", ""),
                    "path": str(path),
                }
            )
        return sorted(result, key=lambda item: item["updated_at"], reverse=True)
