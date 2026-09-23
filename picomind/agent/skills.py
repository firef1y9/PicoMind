"""Workspace and built-in skill discovery."""

from __future__ import annotations

import re
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


class SkillsLoader:
    def __init__(self, workspace: Path) -> None:
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = BUILTIN_SKILLS_DIR

    def list_skills(self) -> list[dict[str, str]]:
        skills: list[dict[str, str]] = []
        seen: set[str] = set()
        for root, source in (
            (self.workspace_skills, "workspace"),
            (self.builtin_skills, "builtin"),
        ):
            if not root.exists():
                continue
            for folder in sorted(root.iterdir()):
                skill_file = folder / "SKILL.md"
                if folder.is_dir() and skill_file.exists() and folder.name not in seen:
                    seen.add(folder.name)
                    skills.append(
                        {"name": folder.name, "path": str(skill_file), "source": source}
                    )
        return skills

    def load_skill(self, name: str) -> str | None:
        for root in (self.workspace_skills, self.builtin_skills):
            path = root / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def build_summary(self) -> str:
        skills = self.list_skills()
        if not skills:
            return ""
        lines = ["<skills>"]
        for skill in skills:
            content = self.load_skill(skill["name"]) or ""
            description = self._frontmatter_value(content, "description") or skill["name"]
            lines.append(
                "  <skill>"
                f"<name>{skill['name']}</name>"
                f"<description>{description}</description>"
                f"<location>{skill['path']}</location>"
                "</skill>"
            )
        lines.append("</skills>")
        return "\n".join(lines)

    @staticmethod
    def _frontmatter_value(content: str, key: str) -> str | None:
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None
        pattern = rf"^{re.escape(key)}:\s*(.+)$"
        found = re.search(pattern, match.group(1), re.MULTILINE)
        return found.group(1).strip().strip("\"'") if found else None
