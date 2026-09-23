import asyncio
import time

import pytest

import picomind.agent.tools.web as web_module
from picomind.agent.tools.web import WebFetchTool, WebSearchTool, _normalize_url
from picomind.config.schema import WebConfig


def test_normalize_markdown_url() -> None:
    assert (
        _normalize_url("[https://example.com/a](https://example.com/a)")
        == "https://example.com/a"
    )


def test_missing_search_key_uses_duckduckgo_directly() -> None:
    config = WebConfig()
    assert WebSearchTool(config)._effective_provider("brave") == "duckduckgo"


@pytest.mark.asyncio
async def test_search_has_hard_timeout() -> None:
    config = WebConfig(search_timeout_seconds=0.05)
    config.search.provider = "duckduckgo"
    config.search.fallback_to_duckduckgo = False
    tool = WebSearchTool(config)

    async def slow_search(query: str, limit: int) -> str:
        await asyncio.sleep(2)
        return query

    tool._duckduckgo = slow_search  # type: ignore[method-assign]
    started = time.perf_counter()
    result = await tool.execute("茂名天气", 1)
    elapsed = time.perf_counter() - started

    assert "超时" in result
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_ddgs_worker_is_killed_on_timeout(monkeypatch) -> None:
    class FakeProcess:
        returncode: int | None = None
        killed = False

        async def communicate(self, payload: bytes) -> tuple[bytes, bytes]:
            await asyncio.sleep(2)
            return b"[]", b""

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            return self.returncode or 0

    process = FakeProcess()

    async def fake_subprocess(*args, **kwargs):
        return process

    monkeypatch.setattr(web_module.asyncio, "create_subprocess_exec", fake_subprocess)
    config = WebConfig(search_timeout_seconds=0.05)
    tool = WebSearchTool(config)

    with pytest.raises(TimeoutError):
        await tool._run_ddgs_worker("test", 1)

    assert process.killed is True


@pytest.mark.asyncio
async def test_fetch_uses_direct_fallback_when_jina_fails() -> None:
    tool = WebFetchTool(WebConfig())

    async def no_jina(url: str) -> None:
        return None

    async def direct(url: str, max_chars: int) -> str:
        return "直连内容"

    tool._jina_reader = no_jina  # type: ignore[method-assign]
    tool._fetch_direct = direct  # type: ignore[method-assign]

    assert await tool.execute("https://example.com") == "直连内容"
