"""Load skill packages from directories.

A skill is a directory containing a SKILL.md entry file:

    <skills_dir>/<name>/
        SKILL.md           — YAML frontmatter (name, description) + prompt body
        references/        — optional supporting docs (not loaded as skills)
        scripts/           — optional scripts

SKILL.md format:
    ---
    name: citadel
    description: "学城文档操作工具"
    ---

    (prompt body here, $ARGUMENTS for user input)

The loader scans directories, reads each SKILL.md, extracts name + description
from frontmatter, and stores the body as prompt_template.
"""

from __future__ import annotations

import re
from pathlib import Path

from agentkit.skills.models import SkillDef

# Builtin skills directory (shipped with package)
BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"


class SkillLoader:
    """Loads skill packages from builtin and user directories.

    Each skill is a directory with a SKILL.md entry file.
    User skills override builtin skills with the same name.
    """

    def __init__(self, user_skills_dir: str | Path | None = None):
        self._builtin_dir = BUILTIN_SKILLS_DIR
        self._user_dir = Path(user_skills_dir).expanduser() if user_skills_dir else None

    def load_all(self) -> dict[str, SkillDef]:
        """Load all skills. User skills override builtin skills with same name."""
        skills: dict[str, SkillDef] = {}

        if self._builtin_dir.exists():
            for skill in self._scan_dir(self._builtin_dir, source="builtin"):
                skills[skill.name] = skill

        if self._user_dir and self._user_dir.exists():
            for skill in self._scan_dir(self._user_dir, source="user"):
                skills[skill.name] = skill

        return skills

    def _scan_dir(self, directory: Path, source: str) -> list[SkillDef]:
        """Scan a directory for skill packages (subdirectories with SKILL.md)."""
        skills = []
        for item in sorted(directory.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue
            skill = self._parse_skill_md(skill_md, dir_name=item.name, source=source)
            if skill:
                skills.append(skill)
        return skills

    @staticmethod
    def _parse_skill_md(path: Path, dir_name: str, source: str) -> SkillDef | None:
        """Parse a SKILL.md file: extract frontmatter + prompt body."""
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        name = dir_name
        description = ""
        body = content

        # Parse YAML frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if fm_match:
            frontmatter_text = fm_match.group(1)
            body = fm_match.group(2)
            for line in frontmatter_text.splitlines():
                line = line.strip()
                if line.lower().startswith("name:"):
                    val = line[len("name:"):].strip().strip('"').strip("'")
                    if val:
                        name = val
                elif line.lower().startswith("description:"):
                    description = line[len("description:"):].strip().strip('"').strip("'")

        if not name:
            return None

        return SkillDef(
            name=name,
            description=description,
            trigger=f"/{name}",
            prompt_template=body.strip(),
            source=source,
        )
