"""Default configuration text and workspace templates."""

from __future__ import annotations

from pathlib import Path

DEFAULT_CONFIG_TOML = """\
[agent.defaults]
workspace = "~/.picomind/workspace"
model = "deepseek-chat"
max_tokens = 8192
context_window_tokens = 65536
temperature = 0.1
max_tool_iterations = 40
max_subagent_iterations = 15
max_concurrent_subagents = 3

[provider]
# 优先使用 PICOMIND_DEEPSEEK_API_KEY，此字段仅作为后备。
api_key = ""
base_url = "https://api.deepseek.com"

[security]
restrict_to_workspace = true

[tools.exec]
enabled = true
timeout = 60
max_output_chars = 10000
path_append = ""

[tools.web]
proxy = ""
request_timeout_seconds = 12
search_timeout_seconds = 10
jina_timeout_seconds = 5

[tools.web.search]
provider = "brave"
api_key = ""
base_url = ""
max_results = 5
fallback_to_duckduckgo = true

[logging]
level = "INFO"
retention = 7
"""

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
WORKSPACE_TEMPLATES = ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md")


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def sync_workspace_templates(workspace: Path) -> list[Path]:
    """Create missing bootstrap files without overwriting user edits."""

    created: list[Path] = []
    workspace.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_TEMPLATES:
        path = workspace / name
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        if write_if_missing(path, content):
            created.append(path)
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    if write_if_missing(memory_dir / "MEMORY.md", "# Long-term Memory\n"):
        created.append(memory_dir / "MEMORY.md")
    if write_if_missing(memory_dir / "HISTORY.md", "# History\n"):
        created.append(memory_dir / "HISTORY.md")
    return created
