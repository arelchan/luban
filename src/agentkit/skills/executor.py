"""Skill matching and prompt building."""

from __future__ import annotations

from agentkit.skills.loader import SkillLoader
from agentkit.skills.models import SkillDef


class SkillExecutor:
    """Matches user input against loaded skills and builds prompts."""

    def __init__(self, loader: SkillLoader):
        self._skills = loader.load_all()

    @property
    def skills(self) -> dict[str, SkillDef]:
        return self._skills

    def match(self, user_input: str) -> tuple[SkillDef, str] | None:
        """Try to match user input against a skill trigger.

        Returns (skill, args_string) if matched, None otherwise.
        """
        parts = user_input.strip().split(maxsplit=1)
        if not parts:
            return None

        cmd = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ""

        for skill in self._skills.values():
            if skill.trigger.lower() == cmd:
                return skill, args_str

        return None

    def build_prompt(self, skill: SkillDef, args: str) -> str:
        """Build the final prompt from the skill template and user args.

        Replaces $ARGUMENTS with the user-provided args string.
        """
        prompt = skill.prompt_template
        if "$ARGUMENTS" in prompt:
            prompt = prompt.replace("$ARGUMENTS", args)
        elif args:
            # If template doesn't have $ARGUMENTS but user passed args, append
            prompt = f"{prompt}\n\n用户参数：{args}"
        return prompt

    def list_skills(self) -> list[SkillDef]:
        """Return all loaded skills."""
        return list(self._skills.values())
