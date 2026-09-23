from pathlib import Path

import pytest

from picomind.agent.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from picomind.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_file_tools_block_sensitive_files(tmp_path: Path) -> None:
    secret = tmp_path / "deepseek api.txt"
    secret.write_text("sk-secret", encoding="utf-8")
    ssh_config = tmp_path / ".ssh" / "config"
    ssh_config.parent.mkdir()
    ssh_config.write_text("Host example", encoding="utf-8")
    reader = ReadFileTool(tmp_path)
    writer = WriteFileTool(tmp_path)

    read_result = await reader.execute(path=str(secret))
    ssh_result = await reader.execute(path=str(ssh_config))
    write_result = await writer.execute(path=".env", content="TOKEN=secret")

    assert "敏感文件" in read_result
    assert "敏感文件" in ssh_result
    assert "敏感文件" in write_result


@pytest.mark.asyncio
async def test_list_dir_hides_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("private", encoding="utf-8")
    (tmp_path / "README.md").write_text("safe", encoding="utf-8")

    result = await ListDirTool(tmp_path).execute(path=".")

    assert "README.md" in result
    assert ".env" not in result
    assert "id_rsa" not in result


@pytest.mark.asyncio
async def test_shell_blocks_sensitive_file_reference(tmp_path: Path) -> None:
    tool = ExecTool(tmp_path)

    result = await tool.execute(command='type "deepseek api.txt"')

    assert "敏感文件" in result
