"""PicoMind command-line interface."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import typer
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from typer import rich_utils as typer_rich_utils
from typer._click import decorators as click_decorators
from typer._click import formatting as click_formatting

from picomind import __logo__, __version__
from picomind.agent.loop import AgentLoop
from picomind.config.defaults import DEFAULT_CONFIG_TOML, sync_workspace_templates
from picomind.config.loader import get_config_path, load_config, set_config_path
from picomind.config.paths import get_cli_history_path, get_logs_dir, resolve_workspace
from picomind.config.schema import Config
from picomind.providers.base import GenerationSettings
from picomind.providers.deepseek import DeepSeekProvider

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")


def _chinese_help_option(param_decls: list[str]):
    def show_help(ctx: Any, param: Any, value: bool) -> None:
        if value and not ctx.resilient_parsing:
            click_decorators.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()

    return click_decorators.option(
        param_decls,
        is_flag=True,
        expose_value=False,
        is_eager=True,
        help="显示帮助信息并退出。",
        callback=show_help,
        required=False,
    )


click_decorators.help_option = _chinese_help_option

_original_write_usage = click_formatting.HelpFormatter.write_usage


def _chinese_write_usage(
    self: click_formatting.HelpFormatter,
    prog: str,
    args: str = "",
    prefix: str | None = None,
) -> None:
    return _original_write_usage(self, prog, args, prefix or "用法：")


click_formatting.HelpFormatter.write_usage = _chinese_write_usage

typer_rich_utils.ARGUMENTS_PANEL_TITLE = "参数"
typer_rich_utils.OPTIONS_PANEL_TITLE = "选项"
typer_rich_utils.COMMANDS_PANEL_TITLE = "命令"
typer_rich_utils.ERRORS_PANEL_TITLE = "错误"
typer_rich_utils.ABORTED_TEXT = "已中止。"
typer_rich_utils.DEFAULT_STRING = "[默认：{}]"
typer_rich_utils.ENVVAR_STRING = "[环境变量：{}]"
typer_rich_utils.REQUIRED_LONG_STRING = "[必填]"

console = Console()
app = typer.Typer(
    name="picomind",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="PicoMind - 可靠的本地个人 AI 助手",
    no_args_is_help=True,
    add_completion=False,
)
session_app = typer.Typer(help="管理已保存的会话")
tools_app = typer.Typer(help="查看已注册工具")
config_app = typer.Typer(help="查看配置")
app.add_typer(session_app, name="session")
app.add_typer(tools_app, name="tools")
app.add_typer(config_app, name="config")

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"{__logo__} PicoMind v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
    ),
    config: str | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="工作区路径"),
) -> None:
    """PicoMind 命令行入口。"""

    config_path = Path(config).expanduser().resolve() if config else None
    if config_path:
        set_config_path(config_path)
    ctx.obj = {"config_path": config_path, "workspace": workspace}


def _runtime_config(ctx: typer.Context) -> tuple[Config, Path]:
    options = ctx.obj or {}
    config_path = options.get("config_path") or get_config_path()
    set_config_path(config_path)
    config = load_config(config_path)
    if options.get("workspace"):
        config.agent.defaults.workspace = str(
            Path(options["workspace"]).expanduser().resolve()
        )
    return config, config_path


def _configure_logging(config: Config) -> None:
    logger.remove()
    logger.add(
        get_logs_dir() / "picomind.log",
        level=config.logging.level.upper(),
        rotation="10 MB",
        retention=config.logging.retention,
        enqueue=True,
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
    )


def _make_provider(config: Config) -> DeepSeekProvider:
    provider = DeepSeekProvider(
        api_key=config.provider.resolved_api_key,
        base_url=config.provider.base_url,
        default_model=config.agent.defaults.model,
    )
    provider.generation = GenerationSettings(
        temperature=config.agent.defaults.temperature,
        max_tokens=config.agent.defaults.max_tokens,
    )
    return provider


def _make_agent(
    ctx: typer.Context,
    *,
    require_key: bool = True,
) -> tuple[AgentLoop, Config, Path]:
    config, config_path = _runtime_config(ctx)
    _configure_logging(config)
    workspace = resolve_workspace(config.agent.defaults.workspace)
    sync_workspace_templates(workspace)
    if require_key and not config.provider.resolved_api_key:
        console.print(
            "[red]缺少 DeepSeek API Key。[/red] "
            "请设置 PICOMIND_DEEPSEEK_API_KEY，或运行 `picomind init`。"
        )
        raise typer.Exit(1)
    agent = AgentLoop(
        config=config,
        provider=_make_provider(config),
        workspace=workspace,
        config_path=config_path,
    )
    return agent, config, config_path


@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="覆盖已有配置"),
) -> None:
    """初始化配置和工作区模板。"""

    options = ctx.obj or {}
    config_path = options.get("config_path") or get_config_path()
    set_config_path(config_path)
    if config_path.exists() and not force:
        console.print(f"[yellow]配置已存在：[/yellow] {config_path}")
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
        console.print(f"[green]已创建配置：[/green] {config_path}")
    config = load_config(config_path)
    workspace = resolve_workspace(options.get("workspace") or config.agent.defaults.workspace)
    created = sync_workspace_templates(workspace)
    console.print(f"[green]工作区已就绪：[/green] {workspace}")
    if created:
        console.print(f"[dim]已创建 {len(created)} 个模板文件。[/dim]")
    if not config.provider.resolved_api_key:
        console.print(
            "开始对话前，请设置 [cyan]PICOMIND_DEEPSEEK_API_KEY[/cyan]。"
        )


async def _chat_loop(
    agent: AgentLoop,
    config: Config,
    session_key: str,
) -> None:
    await agent.start()
    console.print(f"[cyan]{__logo__} PicoMind[/cyan] 会话={session_key}")
    console.print("[dim]输入 /exit 退出，输入 /help 查看命令。[/dim]\n")
    history_path = get_cli_history_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = PromptSession(history=FileHistory(str(history_path)))
    current_model = config.agent.defaults.model
    try:
        while True:
            try:
                raw = await prompt.prompt_async("You: ")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            text = raw.strip()
            if not text:
                continue
            if text.lower() in EXIT_COMMANDS:
                break
            if text == "/help":
                console.print(
                    "/new /resume /clear /model /tools /session /stop /exit"
                )
                continue
            if text == "/new":
                session_key = f"cli:{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                console.print(f"[green]新会话：[/green] {session_key}")
                continue
            if text.startswith("/resume"):
                parts = text.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].strip():
                    console.print("[yellow]用法：[/yellow] /resume <会话键>")
                else:
                    session_key = parts[1].strip()
                    console.print(f"[green]已恢复会话：[/green] {session_key}")
                continue
            if text == "/clear":
                agent.sessions.clear(session_key)
                console.print("[green]会话已清空。[/green]")
                continue
            if text.startswith("/model"):
                parts = text.split(maxsplit=1)
                if len(parts) == 2:
                    current_model = parts[1].strip()
                    agent.model = current_model
                    agent.provider.default_model = current_model
                console.print(f"模型：[cyan]{current_model}[/cyan]")
                continue
            if text == "/tools":
                console.print(", ".join(agent.tools.names))
                continue
            if text == "/session":
                console.print(session_key)
                continue
            if text == "/stop":
                console.print("[dim]当前没有正在运行的命令。[/dim]")
                continue

            printed = False

            async def on_delta(delta: str) -> None:
                nonlocal printed
                if not printed:
                    console.print()
                    console.print("[cyan]PicoMind:[/cyan] ", end="")
                    printed = True
                console.print(delta, end="", markup=False, highlight=False)

            async def on_progress(summary: str) -> None:
                console.print(f"\n  [dim]工具：{summary}[/dim]")

            try:
                final = await _run_agent_with_control(
                    agent,
                    text,
                    session_key=session_key,
                    on_delta=on_delta,
                    on_progress=on_progress,
                    prompt=prompt,
                )
            except KeyboardInterrupt:
                console.print("\n[yellow]已取消。[/yellow]")
                continue
            if final is None:
                console.print("\n[yellow]任务已停止。[/yellow]")
                continue
            if printed:
                console.print("\n")
            else:
                console.print()
                console.print("[cyan]PicoMind:[/cyan]")
                console.print(Markdown(final or ""))
                console.print()
    finally:
        await agent.close()


async def _run_agent_with_control(
    agent: AgentLoop,
    text: str,
    *,
    session_key: str,
    on_delta,
    on_progress,
    prompt: PromptSession,
) -> str | None:
    """Run one request while allowing `/stop` to cancel it."""

    request_task = asyncio.create_task(
        agent.process(
            text,
            session_key=session_key,
            on_delta=on_delta,
            on_progress=on_progress,
        )
    )
    try:
        interactive_output = (
            patch_stdout()
            if sys.stdin.isatty() and sys.stdout.isatty()
            else contextlib.nullcontext()
        )
        with interactive_output:
            while not request_task.done():
                input_task = asyncio.create_task(prompt.prompt_async("运行中> "))
                done, _ = await asyncio.wait(
                    {request_task, input_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if request_task in done:
                    input_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await input_task
                    break
                try:
                    command = (await input_task).strip()
                except (EOFError, KeyboardInterrupt):
                    agent.cancel_active()
                    continue
                if command == "/stop":
                    if agent.cancel_active():
                        console.print("[yellow]正在停止当前任务...[/yellow]")
                    else:
                        console.print("[dim]任务已经结束。[/dim]")
                else:
                    console.print("[dim]任务运行中只接受 /stop。[/dim]")
        try:
            return await request_task
        except asyncio.CancelledError:
            if asyncio.current_task() is not None and asyncio.current_task().cancelling():
                raise
            return None
    except BaseException:
        if not request_task.done():
            request_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await request_task
        raise


@app.command()
def chat(
    ctx: typer.Context,
    session: str = typer.Option("cli:default", "--session", "-s"),
) -> None:
    """启动交互式流式对话。"""

    agent, config, _ = _make_agent(ctx)
    try:
        asyncio.run(_chat_loop(agent, config, session))
    except KeyboardInterrupt:
        console.print("\n[yellow]已停止。[/yellow]")


@app.command()
def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="执行一次的任务"),
    session: str = typer.Option("cli:default", "--session", "-s"),
) -> None:
    """执行一次任务后退出。"""

    agent, _, _ = _make_agent(ctx)

    async def execute() -> str:
        try:
            return await agent.process(task, session_key=session)
        finally:
            await agent.close()

    try:
        result = asyncio.run(execute())
    except KeyboardInterrupt:
        console.print("[yellow]已取消。[/yellow]")
        raise typer.Exit(130)
    console.print(Markdown(result))


@session_app.command("list")
def session_list(ctx: typer.Context) -> None:
    """列出已保存的会话。"""

    config, _ = _runtime_config(ctx)
    workspace = resolve_workspace(config.agent.defaults.workspace)
    from picomind.session.manager import SessionManager

    rows = SessionManager(workspace).list_sessions()
    table = Table("会话键", "更新时间", "文件")
    for row in rows:
        table.add_row(row["key"], row["updated_at"], row["path"])
    console.print(table if rows else "[dim]没有已保存的会话。[/dim]")


@session_app.command("resume")
def session_resume(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="会话键"),
) -> None:
    """恢复指定会话并继续对话。"""

    agent, config, _ = _make_agent(ctx)
    asyncio.run(_chat_loop(agent, config, key))


@session_app.command("clear")
def session_clear(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="会话键"),
) -> None:
    """清空指定会话。"""

    config, _ = _runtime_config(ctx)
    workspace = resolve_workspace(config.agent.defaults.workspace)
    from picomind.session.manager import SessionManager

    SessionManager(workspace).clear(key)
    console.print(f"[green]已清空：[/green] {key}")


@tools_app.command("list")
def tools_list(ctx: typer.Context) -> None:
    """列出当前可用工具。"""

    agent, _, _ = _make_agent(ctx, require_key=False)
    table = Table("工具", "说明")
    for name in agent.tools.names:
        tool = agent.tools.get(name)
        table.add_row(name, tool.description if tool else "")
    console.print(table)


def _redact(value: Any, key: str = "") -> Any:
    sensitive_markers = ("api_key", "token", "secret", "authorization", "cookie", "password")
    if any(marker in key.lower() for marker in sensitive_markers):
        return "已隐藏" if value else ""
    if isinstance(value, dict):
        return {item_key: _redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """显示脱敏后的当前配置。"""

    config, config_path = _runtime_config(ctx)
    console.print(f"[dim]{config_path}[/dim]")
    console.print_json(json.dumps(_redact(config.model_dump(mode="json"))))


@app.command()
def doctor(
    ctx: typer.Context,
    live: bool = typer.Option(False, "--live", help="发起真实 DeepSeek API 请求"),
) -> None:
    """检查配置、凭据、工作区和可选网络连通性。"""

    config, config_path = _runtime_config(ctx)
    workspace = resolve_workspace(config.agent.defaults.workspace)
    checks: list[tuple[str, bool, str]] = [
        ("config", config_path.exists(), str(config_path)),
        ("workspace", workspace.exists(), str(workspace)),
        ("api_key", bool(config.provider.resolved_api_key), "环境变量或配置文件"),
        ("python", sys.version_info >= (3, 11), sys.version.split()[0]),
    ]
    if live and config.provider.resolved_api_key:
        try:
            response = httpx.get(
                config.provider.base_url.rstrip("/") + "/models",
                headers={
                    "Authorization": f"Bearer {config.provider.resolved_api_key}"
                },
                timeout=20,
            )
            checks.append(("deepseek", response.is_success, f"HTTP {response.status_code}"))
        except Exception as exc:
            checks.append(("deepseek", False, str(exc)))
    table = Table("检查项", "状态", "详情")
    for name, ok, detail in checks:
        table.add_row(name, "[green]正常[/green]" if ok else "[red]失败[/red]", detail)
    console.print(table)
    if not all(item[1] for item in checks):
        raise typer.Exit(1)
