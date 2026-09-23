import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from picomind.agent.tools.mcp import _transport, connect_mcp_servers
from picomind.agent.tools.registry import ToolRegistry
from picomind.config.schema import MCPServerConfig


def test_mcp_transport_selection() -> None:
    assert _transport(MCPServerConfig(command="python")) == "stdio"
    assert _transport(MCPServerConfig(url="https://example.com/sse")) == "sse"
    assert (
        _transport(MCPServerConfig(url="https://example.com/mcp"))
        == "streamableHttp"
    )


@pytest.mark.asyncio
async def test_stdio_mcp_server_registration_and_call(tmp_path: Path) -> None:
    server = tmp_path / "server.py"
    server.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("picomind-test")

@mcp.tool()
def echo(text: str) -> str:
    return text

if __name__ == "__main__":
    mcp.run()
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        await connect_mcp_servers(
            {
                "test": MCPServerConfig(
                    type="stdio",
                    command=sys.executable,
                    args=[str(server)],
                    tool_timeout=10,
                )
            },
            registry,
            stack,
        )

        assert "mcp_test_echo" in registry.names
        assert await registry.execute("mcp_test_echo", {"text": "hello"}) == "hello"
