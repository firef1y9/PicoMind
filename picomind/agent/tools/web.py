"""Web search and fetch tools."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from picomind.agent.tools.base import Tool
from picomind.config.schema import WebConfig
from picomind.security.network import validate_url


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = html.unescape(" ".join(self.parts))
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def _client(config: WebConfig) -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "timeout": config.request_timeout_seconds,
        "follow_redirects": False,
        "headers": {"User-Agent": "PicoMind/0.1"},
    }
    if config.proxy:
        kwargs["proxy"] = config.proxy
    return httpx.AsyncClient(**kwargs)


async def _safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    current = url
    for _ in range(6):
        ok, reason = await asyncio.wait_for(
            asyncio.to_thread(validate_url, current),
            timeout=3.0,
        )
        if not ok:
            raise ValueError(reason)
        response = await client.get(current, headers=headers)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response
            current = urljoin(current, location)
            continue
        return response
    raise ValueError("重定向次数过多")


def _normalize_url(raw: str) -> str:
    """Accept plain URLs and common Markdown link forms."""

    text = raw.strip().strip("<>`")
    match = re.match(
        r"^\[(https?://[^\]]+)\]\((https?://[^)]+)\)$",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(2).strip()
    return text


class WebSearchTool(Tool):
    timeout_seconds = None

    def __init__(self, config: WebConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索网页，返回标题、网址和摘要。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        }

    def timeout_for(self, params: dict[str, Any]) -> float:
        return max(1.0, self.config.search_timeout_seconds) * 2 + 3.0

    async def execute(self, query: str, max_results: int = 5, **_: Any) -> str:
        search = self.config.search
        limit = min(max_results, search.max_results)
        provider = self._effective_provider(search.provider)
        try:
            return await self._run_provider(provider, query, limit)
        except TimeoutError:
            if search.fallback_to_duckduckgo and provider != "duckduckgo":
                try:
                    return await self._run_provider("duckduckgo", query, limit)
                except Exception as exc:
                    return (
                        f"Error: 网络搜索超时（{provider}），"
                        f"回退 DuckDuckGo 也失败：{exc}。"
                        "请勿立即重复相同搜索；优先直接抓取已知权威网址，"
                        "或配置 Brave/Tavily。"
                    )
            return (
                f"Error: 网络搜索超时（{provider}，"
                f"{self.config.search_timeout_seconds:g} 秒上限）。"
                "请勿立即重复相同搜索；优先直接抓取已知权威网址，"
                "或配置 Brave/Tavily。"
            )
        except Exception as exc:
            if search.fallback_to_duckduckgo and provider != "duckduckgo":
                try:
                    return await self._run_provider("duckduckgo", query, limit)
                except Exception as fallback_exc:
                    return (
                        f"Error: 网络搜索失败（{provider}）：{exc}；"
                        f"回退 DuckDuckGo 也失败：{fallback_exc}"
                    )
            return f"Error: 网络搜索失败（{provider}）：{exc}"

    def _effective_provider(self, provider: str) -> str:
        search = self.config.search
        if not search.fallback_to_duckduckgo:
            return provider
        missing_credentials = (
            provider in {"brave", "tavily", "jina"} and not search.resolved_api_key
        )
        missing_searxng = provider == "searxng" and not search.resolved_api_key
        return "duckduckgo" if missing_credentials or missing_searxng else provider

    async def _run_provider(self, provider: str, query: str, limit: int) -> str:
        timeout = max(0.5, self.config.search_timeout_seconds)
        async with asyncio.timeout(timeout):
            if provider == "duckduckgo":
                return await self._duckduckgo(query, limit)
            if provider == "brave":
                return await self._brave(query, limit)
            if provider == "tavily":
                return await self._tavily(query, limit)
            if provider == "searxng":
                return await self._searxng(query, limit)
            if provider == "jina":
                return await self._jina(query, limit)
            raise ValueError(f"未知搜索服务：{provider}")

    async def _brave(self, query: str, limit: int) -> str:
        api_key = self.config.search.resolved_api_key
        if not api_key:
            return await self._duckduckgo(query, limit)
        async with _client(self.config) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": api_key},
            )
            response.raise_for_status()
            results = response.json().get("web", {}).get("results", [])
        return self._format(results)

    async def _tavily(self, query: str, limit: int) -> str:
        api_key = self.config.search.resolved_api_key
        if not api_key:
            return await self._duckduckgo(query, limit)
        async with _client(self.config) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": limit},
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        return self._format(results)

    async def _searxng(self, query: str, limit: int) -> str:
        base_url = self.config.search.resolved_api_key
        if not base_url:
            return await self._duckduckgo(query, limit)
        async with _client(self.config) as client:
            response = await client.get(
                base_url.rstrip("/") + "/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            results = response.json().get("results", [])[:limit]
        return self._format(results)

    async def _jina(self, query: str, limit: int) -> str:
        api_key = self.config.search.resolved_api_key
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with _client(self.config) as client:
            response = await client.get(
                "https://s.jina.ai/",
                params={"q": query},
                headers=headers,
            )
            response.raise_for_status()
            text = response.text
        return text[: max(1000, limit * 1000)]

    async def _duckduckgo(self, query: str, limit: int) -> str:
        results = await self._run_ddgs_worker(query, limit)
        return self._format(results)

    async def _run_ddgs_worker(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Run DDGS in a killable subprocess so a stuck request cannot block PicoMind."""

        timeout = max(0.5, self.config.search_timeout_seconds)
        payload = json.dumps({"query": query, "limit": limit, "timeout": timeout}).encode(
            "utf-8"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "picomind.agent.tools.ddgs_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload),
                timeout=timeout + 0.5,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"DuckDuckGo 搜索超过 {timeout:g} 秒")
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail[:500] or f"DDGS 子进程退出码 {process.returncode}")
        try:
            data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("DDGS 子进程返回了无效数据") from exc
        if not isinstance(data, list):
            raise RuntimeError("DDGS 子进程返回格式不正确")
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _format(results: list[dict[str, Any]]) -> str:
        if not results:
            return "没有搜索结果。"
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            title = item.get("title") or item.get("name") or "（无标题）"
            url = item.get("url") or item.get("href") or ""
            snippet = (
                item.get("description")
                or item.get("body")
                or item.get("content")
                or item.get("snippet")
                or ""
            )
            lines.append(f"{index}. {title}\n{url}\n{snippet}".strip())
        return "\n\n".join(lines)


class WebFetchTool(Tool):
    timeout_seconds = None

    def __init__(self, config: WebConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "抓取公开网址，并返回提取后的正文。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 100000},
            },
            "required": ["url"],
        }

    def timeout_for(self, params: dict[str, Any]) -> float:
        return (
            max(1.0, self.config.jina_timeout_seconds)
            + max(1.0, self.config.request_timeout_seconds)
            + 3.0
        )

    async def execute(self, url: str, max_chars: int = 20000, **_: Any) -> str:
        url = _normalize_url(url)
        try:
            ok, reason = await asyncio.wait_for(
                asyncio.to_thread(validate_url, url),
                timeout=3.0,
            )
        except TimeoutError:
            return "Error: URL 安全检查超时"
        if not ok:
            return f"Error: 不安全的 URL：{reason}"
        jina = await self._jina_reader(url)
        if jina:
            return jina[:max_chars]
        return await self._fetch_direct(url, max_chars)

    async def _fetch_direct(self, url: str, max_chars: int) -> str:
        timeout = max(1.0, self.config.request_timeout_seconds)
        try:
            async with asyncio.timeout(timeout):
                async with _client(self.config) as client:
                    response = await _safe_get(client, url)
                    response.raise_for_status()
        except TimeoutError:
            return f"抓取 URL 超时（超过 {timeout:g} 秒）：{url}"
        except Exception as exc:
            return f"抓取 URL 失败：{exc}"
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            parser = _TextExtractor()
            parser.feed(response.text)
            text = parser.text()
        else:
            text = response.text
        return text[:max_chars] or "（响应内容为空）"

    async def _jina_reader(self, url: str) -> str | None:
        timeout = max(1.0, self.config.jina_timeout_seconds)
        try:
            async with asyncio.timeout(timeout):
                async with _client(self.config) as client:
                    response = await client.get(f"https://r.jina.ai/{url}")
                    if response.is_success and response.text.strip():
                        return response.text
        except Exception:
            return None
        return None
