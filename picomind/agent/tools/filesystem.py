"""Workspace-scoped filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from picomind.agent.tools.base import Tool
from picomind.security.secrets import is_sensitive_directory, is_sensitive_path


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class _FilesystemTool(Tool):
    timeout_seconds = 30.0

    def __init__(
        self,
        workspace: Path,
        restrict_to_workspace: bool = True,
        read_only_roots: list[Path] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.restrict_to_workspace = restrict_to_workspace
        self.read_only_roots = [path.resolve() for path in (read_only_roots or [])]

    def resolve(self, raw_path: str, *, write: bool = False) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if not self.restrict_to_workspace:
            allowed = True
        else:
            allowed = _is_under(resolved, self.workspace) or (
                not write and any(_is_under(resolved, root) for root in self.read_only_roots)
            )
        if not allowed:
            raise PermissionError(f"路径位于允许的工作区之外：{resolved}")
        if is_sensitive_directory(resolved) or is_sensitive_path(resolved):
            raise PermissionError(f"该路径被识别为敏感文件，禁止通过工具访问：{resolved.name}")
        return resolved


class ReadFileTool(_FilesystemTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取 UTF-8 文本文件，并返回带行号的内容。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int = 2000,
        **_: Any,
    ) -> str:
        try:
            target = self.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not target.is_file():
            return f"Error: 文件不存在：{path}"
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: {path} 不是 UTF-8 文本文件"
        lines = content.splitlines()
        start = max(offset - 1, 0)
        selected = lines[start : start + limit]
        numbered = [f"{start + index + 1}| {line}" for index, line in enumerate(selected)]
        end = start + len(selected)
        footer = (
            f"\n\n（显示第 {offset}-{end} 行，共 {len(lines)} 行）"
            if end < len(lines)
            else f"\n\n（文件结束，共 {len(lines)} 行）"
        )
        return "\n".join(numbered) + footer


class WriteFileTool(_FilesystemTool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "将 UTF-8 文本写入文件，必要时自动创建父目录。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **_: Any) -> str:
        try:
            target = self.resolve(path, write=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            return f"已写入 {len(content.encode('utf-8'))} 字节：{target}"
        except Exception as exc:
            return f"写入文件失败：{exc}"


class EditFileTool(_FilesystemTool):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "在 UTF-8 文件中替换精确匹配的文本。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        **_: Any,
    ) -> str:
        try:
            target = self.resolve(path, write=True)
            if not target.is_file():
                return f"Error: 文件不存在：{path}"
            content = target.read_text(encoding="utf-8")
            count = content.count(old_text)
            if count == 0:
                return "Error: 未找到 old_text"
            if count > 1 and not replace_all:
                return f"Error: old_text 出现了 {count} 次，请增加上下文或将 replace_all 设为 true"
            updated = content.replace(old_text, new_text, -1 if replace_all else 1)
            target.write_text(updated, encoding="utf-8", newline="\n")
            return f"已编辑 {target}；替换次数={count if replace_all else 1}"
        except Exception as exc:
            return f"编辑文件失败：{exc}"


class ListDirTool(_FilesystemTool):
    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "列出工作区内的文件和目录。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["path"],
        }

    _IGNORED = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
    }

    async def execute(
        self,
        path: str,
        recursive: bool = False,
        max_entries: int = 200,
        **_: Any,
    ) -> str:
        try:
            root = self.resolve(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        if not root.is_dir():
            return f"Error: 目录不存在：{path}"
        iterator = root.rglob("*") if recursive else root.iterdir()
        items: list[str] = []
        total = 0
        for item in sorted(iterator):
            if any(part in self._IGNORED for part in item.parts):
                continue
            if is_sensitive_directory(item) or is_sensitive_path(item):
                continue
            total += 1
            if len(items) >= max_entries:
                continue
            relative = item.relative_to(root)
            items.append(f"{relative}/" if item.is_dir() else str(relative))
        if total > max_entries:
            items.append(f"... 另有 {total - max_entries} 项")
        return "\n".join(items) or "（空目录）"
