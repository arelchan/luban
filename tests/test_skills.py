"""Tests for agentkit.skills — loader, executor."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentkit.skills.executor import SkillExecutor
from agentkit.skills.loader import SkillLoader


class TestSkillLoader:
    def test_load_builtin_skills(self):
        loader = SkillLoader()
        skills = loader.load_all()
        assert "commit" in skills
        assert "review" in skills
        assert "explain" in skills
        assert "find-skills" in skills

    def test_find_skills_builtin(self):
        loader = SkillLoader()
        skills = loader.load_all()
        fs = skills["find-skills"]
        assert fs.trigger == "/find-skills"
        assert fs.source == "builtin"
        assert "$ARGUMENTS" in fs.prompt_template
        assert "OpenClaw" in fs.prompt_template

    def test_builtin_skill_fields(self):
        loader = SkillLoader()
        skills = loader.load_all()
        commit = skills["commit"]
        assert commit.trigger == "/commit"
        assert commit.source == "builtin"
        assert commit.description != ""
        assert "$ARGUMENTS" in commit.prompt_template

    def test_user_skills_override(self):
        with tempfile.TemporaryDirectory() as td:
            # Create a user skill that overrides commit
            skill_dir = Path(td) / "commit"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: commit\ndescription: Custom commit\n---\nCustom prompt: $ARGUMENTS\n",
                encoding="utf-8",
            )
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            assert skills["commit"].source == "user"
            assert "Custom prompt" in skills["commit"].prompt_template

    def test_user_skills_add_new(self):
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "deploy"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: deploy\ndescription: Deploy to prod\n---\nDeploy now: $ARGUMENTS\n",
                encoding="utf-8",
            )
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            assert "deploy" in skills
            assert "commit" in skills  # Builtin still loaded

    def test_name_from_frontmatter_overrides_dirname(self):
        """frontmatter name: overrides directory name."""
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "my-dir"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: actual-name\ndescription: test\n---\nBody\n",
                encoding="utf-8",
            )
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            assert "actual-name" in skills
            assert skills["actual-name"].trigger == "/actual-name"

    def test_no_frontmatter(self):
        """SKILL.md without frontmatter — body is the whole file."""
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "simple"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("Just do the thing: $ARGUMENTS\n", encoding="utf-8")
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            assert "simple" in skills
            assert skills["simple"].description == ""
            assert "Just do the thing" in skills["simple"].prompt_template

    def test_ignores_dirs_without_skill_md(self):
        """Directories without SKILL.md are ignored."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "not-a-skill").mkdir()
            (Path(td) / "not-a-skill" / "readme.md").write_text("hello", encoding="utf-8")
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            # Only builtins
            assert "not-a-skill" not in skills

    def test_ignores_hidden_dirs(self):
        """Hidden directories (starting with .) are skipped."""
        with tempfile.TemporaryDirectory() as td:
            hidden = Path(td) / ".hidden"
            hidden.mkdir()
            (hidden / "SKILL.md").write_text("---\nname: hidden\n---\nBody\n", encoding="utf-8")
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            assert "hidden" not in skills

    def test_empty_user_dir(self):
        with tempfile.TemporaryDirectory() as td:
            loader = SkillLoader(user_skills_dir=td)
            skills = loader.load_all()
            # Should still have builtins
            assert len(skills) >= 3

    def test_nonexistent_user_dir(self):
        loader = SkillLoader(user_skills_dir="/tmp/nonexistent_skills_dir_xyz")
        skills = loader.load_all()
        # Should still have builtins
        assert len(skills) >= 3


class TestSkillExecutor:
    def _make_executor(self) -> SkillExecutor:
        loader = SkillLoader()
        return SkillExecutor(loader)

    def test_match_builtin(self):
        exe = self._make_executor()
        result = exe.match("/commit fix typo")
        assert result is not None
        skill, args = result
        assert skill.name == "commit"
        assert args == "fix typo"

    def test_match_no_args(self):
        exe = self._make_executor()
        result = exe.match("/review")
        assert result is not None
        skill, args = result
        assert skill.name == "review"
        assert args == ""

    def test_match_case_insensitive(self):
        exe = self._make_executor()
        result = exe.match("/COMMIT hello")
        assert result is not None
        assert result[0].name == "commit"

    def test_no_match(self):
        exe = self._make_executor()
        result = exe.match("/nonexistent_skill_xyz")
        assert result is None

    def test_build_prompt_with_args(self):
        exe = self._make_executor()
        result = exe.match("/commit fix: typo in readme")
        assert result is not None
        skill, args = result
        prompt = exe.build_prompt(skill, args)
        assert "fix: typo in readme" in prompt
        assert "$ARGUMENTS" not in prompt  # Placeholder replaced

    def test_build_prompt_no_args(self):
        exe = self._make_executor()
        result = exe.match("/explain")
        assert result is not None
        skill, args = result
        prompt = exe.build_prompt(skill, args)
        assert len(prompt) > 0

    def test_match_find_skills(self):
        exe = self._make_executor()
        result = exe.match("/find-skills weather")
        assert result is not None
        skill, args = result
        assert skill.name == "find-skills"
        assert args == "weather"

    def test_list_skills(self):
        exe = self._make_executor()
        skills = exe.list_skills()
        assert len(skills) >= 5
        names = [s.name for s in skills]
        assert "commit" in names
        assert "review" in names
        assert "explain" in names
        assert "find-skills" in names
