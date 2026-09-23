"""Workspace-aware shell execution tool."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from pathlib import Path
from typing import Any

from picomind.agent.tools.base import Tool
from picomind.security.network import contains_internal_url
from picomind.security.secrets import find_sensitive_reference


class ExecTool(Tool):
    timeout_seconds = None

    _DENY = (
        r"\brm\s+-[rf]{1,2}\b",
        r"\bdel\s+/[fq]\b",
        r"\brmdir\s+/s\b",
        r"(?:^|[;&|]\s*)format\b",
        r"\b(mkfs|diskpart)\b",
        r"\bdd\s+if=",
        r"\b(shutdown|reboot|poweroff)\b",
    )
    _WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'|><;]+")
    _POSIX_PATH = re.compile(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)")

    def __init__(
        self,
        workspace: Path,
        timeout: int = 60,
        max_output_chars: int = 10_000,
        restrict_to_workspace: bool = True,
        path_append: str = "",
    ) -> None:
        self.workspace = workspace.resolve()
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "在工作区内执行 Shell 命令，并返回标准输出、标准错误和退出码。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "working_dir": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            "required": ["command"],
        }

    def timeout_for(self, params: dict[str, Any]) -> float:
        requested = params.get("timeout") or self.timeout
        return min(float(requested), 600.0) + 2.0

    def _guard(self, command: str, cwd: Path) -> str | None:
        lowered = command.lower()
        sensitive = find_sensitive_reference(command)
        if sensitive:
            return f"Error: 命令涉及敏感文件，已拦截：{sensitive}"
        if any(re.search(pattern, lowered) for pattern in self._DENY):
            return "Error: 命令被安全防护拦截"
        if contains_internal_url(command):
            return "Error: 命令包含内部或私有地址，已拦截"
        if not self.restrict_to_workspace:
            return None
        if "../" in command or "..\\" in command:
            return "Error: 命令包含路径穿越，已拦截"
        raw_paths = self._WINDOWS_PATH.findall(command) + self._POSIX_PATH.findall(command)
        for raw in raw_paths:
            try:
                resolved = Path(os.path.expandvars(raw)).expanduser().resolve()
            except OSError:
                continue
            if resolved != cwd and cwd not in resolved.parents:
                return f"Error: 命令访问了工作区之外的路径：{resolved}"
        return None

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        **_: Any,
    ) -> str:
        cwd = Path(working_dir).expanduser().resolve() if working_dir else self.workspace
        if self.restrict_to_workspace and cwd != self.workspace and self.workspace not in cwd.parents:
            return "Error: 工作目录位于工作区之外"
        blocked = self._guard(command, cwd)
        if blocked:
            return blocked
        effective_timeout = min(timeout or self.timeout, 600)
        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=effective_timeout
                )
            except asyncio.TimeoutError:
                await self._terminate_process(process)
                return f"Error: 命令执行超过 {effective_timeout} 秒，已超时"
            except asyncio.CancelledError:
                await self._terminate_process(process)
                raise
        except Exception as exc:
            return f"启动命令失败：{exc}"
        parts: list[str] = []
        if stdout:
            parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            parts.append("STDERR:\n" + stderr.decode("utf-8", errors="replace"))
        parts.append(f"退出码：{process.returncode}")
        result = "\n".join(parts)
        if len(result) > self.max_output_chars:
            half = self.max_output_chars // 2
            result = result[:half] + "\n... 输出已截断 ...\n" + result[-half:]
        return result

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if sys.platform == "win32":
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=5.0)
            except (FileNotFoundError, TimeoutError, OSError):
                pass
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        with contextlib.suppress(ProcessLookupError):
            await asyncio.wait_for(process.wait(), timeout=5.0)
