import os

import pytest

from picomind.providers.deepseek import DeepSeekProvider


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_deepseek_chat() -> None:
    if os.getenv("PICOMIND_RUN_LIVE_TESTS") != "1":
        pytest.skip("set PICOMIND_RUN_LIVE_TESTS=1 to run live tests")
    key = os.getenv("PICOMIND_DEEPSEEK_API_KEY", "").strip()
    if not key:
        pytest.skip("PICOMIND_DEEPSEEK_API_KEY is not set")
    provider = DeepSeekProvider(api_key=key)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "Reply with exactly: PICO_OK"}],
        model="deepseek-chat",
        max_tokens=32,
        temperature=0,
    )

    assert response.finish_reason != "error"
    assert "PICO_OK" in (response.content or "")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_deepseek_stream() -> None:
    if os.getenv("PICOMIND_RUN_LIVE_TESTS") != "1":
        pytest.skip("set PICOMIND_RUN_LIVE_TESTS=1 to run live tests")
    key = os.getenv("PICOMIND_DEEPSEEK_API_KEY", "").strip()
    if not key:
        pytest.skip("PICOMIND_DEEPSEEK_API_KEY is not set")
    provider = DeepSeekProvider(api_key=key)
    deltas: list[str] = []

    async def collect(delta: str) -> None:
        deltas.append(delta)

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "Reply with exactly: PICO_STREAM_OK"}],
        model="deepseek-chat",
        max_tokens=32,
        temperature=0,
        on_content_delta=collect,
    )

    assert response.finish_reason != "error"
    assert "PICO_STREAM_OK" in "".join(deltas)
