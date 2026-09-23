from pathlib import Path

from picomind.agent.context import ContextBuilder
from picomind.agent.memory import MemoryStore
from picomind.agent.skills import SkillsLoader
from picomind.config.defaults import sync_workspace_templates


def test_workspace_templates_and_context(tmp_path: Path) -> None:
    sync_workspace_templates(tmp_path)

    context = ContextBuilder(tmp_path).system_prompt()

    assert "PicoMind" in context
    assert "工作区规则" in context
    assert "summarize" in context


def test_memory_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.replace("# Long-term Memory\n\nUser prefers concise answers.")
    store.append_history("[2026-09-23 10:00] user preference")

    assert "concise" in store.context()
    assert "user preference" in store.history_file.read_text(encoding="utf-8")


def test_workspace_skill_overrides_builtin(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "summarize"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: summarize\ndescription: custom summary skill\n---\n",
        encoding="utf-8",
    )
    loader = SkillsLoader(tmp_path)

    matched = [item for item in loader.list_skills() if item["name"] == "summarize"]

    assert len(matched) == 1
    assert matched[0]["source"] == "workspace"
