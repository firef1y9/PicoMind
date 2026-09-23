from typer.testing import CliRunner

from picomind.cli import app


def test_help_output_is_chinese() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "用法：" in result.output
    assert "选项" in result.output
    assert "命令" in result.output
    assert "显示帮助信息并退出" in result.output
    assert "Show this message" not in result.output
