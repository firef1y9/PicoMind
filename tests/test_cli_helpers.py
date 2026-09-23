from picomind.cli import _redact


def test_redact_hides_credentials_recursively() -> None:
    value = {
        "provider": {"api_key": "secret"},
        "headers": {"auth_token": "secret"},
        "mcp": {"headers": {"Authorization": "Bearer secret"}},
        "safe": "visible",
    }

    redacted = _redact(value)

    assert redacted["provider"]["api_key"] == "已隐藏"
    assert redacted["headers"]["auth_token"] == "已隐藏"
    assert redacted["mcp"]["headers"]["Authorization"] == "已隐藏"
    assert redacted["safe"] == "visible"
