from pathlib import Path

from picomind.config.loader import load_config, save_config
from picomind.config.schema import Config


def test_config_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PICOMIND_DEEPSEEK_API_KEY", "env-key")
    path = tmp_path / "config.toml"
    config = Config()
    config.provider.api_key = "file-key"
    config.agent.defaults.model = "deepseek-chat"
    save_config(config, path)

    loaded = load_config(path)

    assert loaded.agent.defaults.model == "deepseek-chat"
    assert loaded.provider.resolved_api_key == "env-key"
    assert "restrict_to_workspace" in path.read_text(encoding="utf-8")


def test_missing_config_returns_defaults(tmp_path: Path) -> None:
    loaded = load_config(tmp_path / "missing.toml")

    assert loaded.agent.defaults.model == "deepseek-chat"
    assert loaded.security.restrict_to_workspace is True
