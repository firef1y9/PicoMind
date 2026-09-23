import asyncio
from pathlib import Path

import pytest

from picomind.agent.tools.filesystem import ReadFileTool, WriteFileTool
from picomind.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_filesystem_tools_stay_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = WriteFileTool(workspace)
    reader = ReadFileTool(workspace)

    result = await writer.execute(path="notes/test.txt", content="hello")
    assert "已写入" in result
    assert "hello" in await reader.execute(path="notes/test.txt")

    outside = await reader.execute(path=str(tmp_path / "outside.txt"))
    assert "工作区之外" in outside


@pytest.mark.asyncio
async def test_shell_blocks_destructive_commands(tmp_path: Path) -> None:
    tool = ExecTool(tmp_path)

    result = await tool.execute(command="rm -rf .")

    assert "拦截" in result


@pytest.mark.asyncio
async def test_shell_executes_normal_command(tmp_path: Path) -> None:
    tool = ExecTool(tmp_path, timeout=10)

    result = await tool.execute(command="echo picomind")

    assert "picomind" in result
    assert "退出码：0" in result


@pytest.mark.asyncio
async def test_shell_timeout(tmp_path: Path) -> None:
    tool = ExecTool(tmp_path, timeout=1)
    command = "ping 127.0.0.1 -n 3 > NUL" if asyncio.sys.platform == "win32" else "sleep 3"

    result = await tool.execute(command=command, timeout=1)

    assert "超时" in result
