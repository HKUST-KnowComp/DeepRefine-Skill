"""Integration tests for OpenCode skill — CLI layer + frontmatter validation."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_OPENCODE = REPO_ROOT / "deeprefine_skill" / "SKILL_OPENCODE.md"
COMMANDS_DIR = REPO_ROOT / "deeprefine_skill" / "commands" / "opencode"
EXPECTED_COMMANDS: tuple[str, ...] = (
    "deeprefine.md",
    "deeprefine-review.md",
    "deeprefine-apply.md",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file (between ``---`` fences)."""
    parts = text.split("---")
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``python -m deeprefine_skill.cli`` with given args."""
    cmd = [sys.executable, "-m", "deeprefine_skill.cli", *args]
    return subprocess.run(
        cmd,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
    )


def _tmp_opencode_dir(tmp_path: Path) -> Path:
    """Create a fake .opencode layout and return that directory."""
    return tmp_path / ".opencode"


# ---------------------------------------------------------------------------
# Frontmatter tests (no filesystem side-effects)
# ---------------------------------------------------------------------------


class TestSkillFrontmatter:
    """Verify SKILL_OPENCODE.md frontmatter satisfies OpenCode skill spec."""

    def test_name_field_present(self) -> None:
        """Required field: ``name`` (1-64 chars, lowercase alphanumeric + hyphens)."""
        text = SKILL_OPENCODE.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert "name" in fm, "missing required 'name' field"
        name: str = fm["name"]
        assert 1 <= len(name) <= 64, f"name length {len(name)} out of range [1,64]"
        assert name == "deeprefine"

    def test_description_field_present(self) -> None:
        """Required field: ``description`` (1-1024 chars)."""
        text = SKILL_OPENCODE.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert "description" in fm, "missing required 'description' field"
        desc = fm["description"]
        if isinstance(desc, str):
            assert 1 <= len(desc) <= 1024, f"description length {len(desc)} out of range [1,1024]"

    def test_disable_model_invocation_absent(self) -> None:
        """Cursor-specific field must NOT leak into OpenCode skill."""
        text = SKILL_OPENCODE.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert "disable-model-invocation" not in fm, (
            "disable-model-invocation is Cursor-only and must not appear in OpenCode SKILL.md"
        )

    def test_license_field(self) -> None:
        """Optional field: ``license`` should be MIT."""
        text = SKILL_OPENCODE.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert fm.get("license") == "MIT"

    def test_compatibility_field(self) -> None:
        """Metadata field: ``compatibility`` should reference opencode."""
        text = SKILL_OPENCODE.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert "compatibility" in fm
        assert "opencode" in str(fm["compatibility"]).lower()


class TestCommandFrontmatter:
    """Verify each command .md has valid YAML frontmatter."""

    @pytest.mark.parametrize("cmd_name", EXPECTED_COMMANDS)
    def test_command_has_description(self, cmd_name: str) -> None:
        """Every command must have a ``description`` in its frontmatter."""
        cmd_path = COMMANDS_DIR / cmd_name
        assert cmd_path.is_file(), f"command file missing: {cmd_path}"
        fm = _parse_frontmatter(cmd_path.read_text(encoding="utf-8"))
        assert "description" in fm, f"{cmd_name}: missing 'description' field"
        assert len(str(fm["description"])) > 0

    @pytest.mark.parametrize("cmd_name", EXPECTED_COMMANDS)
    def test_command_loads_skill(self, cmd_name: str) -> None:
        """Every command should reference ``skill(name=\"deeprefine\")``."""
        cmd_path = COMMANDS_DIR / cmd_name
        body = cmd_path.read_text(encoding="utf-8")
        assert 'skill(name="deeprefine")' in body, (
            f"{cmd_name}: missing skill(name=\"deeprefine\") invocation"
        )


# ---------------------------------------------------------------------------
# Installer tests (temporary directories, no side-effects)
# ---------------------------------------------------------------------------


class TestOpencodeInstall:
    """End-to-end install/uninstall in isolated temp dirs."""

    def _run_install(self, cwd: Path, *, project: bool = True) -> subprocess.CompletedProcess[str]:
        args = ["opencode", "install"]
        if project:
            args.append("--project")
        return _run_cli(*args, cwd=cwd)

    def _run_uninstall(self, cwd: Path, *, project: bool = True) -> subprocess.CompletedProcess[str]:
        args = ["opencode", "uninstall"]
        if project:
            args.append("--project")
        return _run_cli(*args, cwd=cwd)

    def test_install_creates_skill_file(self, tmp_path: Path) -> None:
        """Install creates .opencode/skills/deeprefine/SKILL.md."""
        skill_dest = tmp_path / ".opencode" / "skills" / "deeprefine" / "SKILL.md"
        result = self._run_install(cwd=tmp_path)
        assert result.returncode == 0, f"install failed: {result.stderr}"
        assert skill_dest.is_file(), f"SKILL.md not created at {skill_dest}"

    def test_install_creates_command_files(self, tmp_path: Path) -> None:
        """Install creates all 3 command files under .opencode/commands/."""
        result = self._run_install(cwd=tmp_path)
        assert result.returncode == 0, f"install failed: {result.stderr}"
        for cmd_name in EXPECTED_COMMANDS:
            cmd_path = tmp_path / ".opencode" / "commands" / cmd_name
            assert cmd_path.is_file(), f"command {cmd_name} not created at {cmd_path}"

    def test_uninstall_removes_skill_file(self, tmp_path: Path) -> None:
        """Uninstall removes .opencode/skills/deeprefine/SKILL.md."""
        self._run_install(cwd=tmp_path)
        skill_dest = tmp_path / ".opencode" / "skills" / "deeprefine" / "SKILL.md"
        assert skill_dest.is_file(), "precondition: install must succeed"

        result = self._run_uninstall(cwd=tmp_path)
        assert result.returncode == 0, f"uninstall failed: {result.stderr}"
        assert not skill_dest.exists(), f"SKILL.md not removed: {skill_dest}"

    def test_uninstall_removes_command_files(self, tmp_path: Path) -> None:
        """Uninstall removes all deeprefine*.md command files."""
        self._run_install(cwd=tmp_path)
        for cmd_name in EXPECTED_COMMANDS:
            assert (tmp_path / ".opencode" / "commands" / cmd_name).is_file()

        result = self._run_uninstall(cwd=tmp_path)
        assert result.returncode == 0
        for cmd_name in EXPECTED_COMMANDS:
            cmd_path = tmp_path / ".opencode" / "commands" / cmd_name
            assert not cmd_path.exists(), f"command {cmd_name} not removed"

    def test_uninstall_clean_dirs(self, tmp_path: Path) -> None:
        """Uninstall cleans up empty parent directories."""
        self._run_install(cwd=tmp_path)
        self._run_uninstall(cwd=tmp_path)

        # Commands dir may remain if other commands exist, but skill deep-dirs should be gone
        skill_deep_dir = tmp_path / ".opencode" / "skills" / "deeprefine"
        assert not skill_deep_dir.exists(), f"skill dir not cleaned: {skill_deep_dir}"

    def test_install_idempotent(self, tmp_path: Path) -> None:
        """Install twice should succeed (overwrite)."""
        r1 = self._run_install(cwd=tmp_path)
        r2 = self._run_install(cwd=tmp_path)
        assert r1.returncode == 0
        assert r2.returncode == 0, f"second install failed: {r2.stderr}"
        skill_dest = tmp_path / ".opencode" / "skills" / "deeprefine" / "SKILL.md"
        assert skill_dest.is_file()


# ---------------------------------------------------------------------------
# CLI help tests
# ---------------------------------------------------------------------------


class TestCliHelp:
    """Verify CLI --help output for opencode subcommands."""

    def test_opencode_help_shows_subcommands(self) -> None:
        """``deeprefine opencode --help`` shows install and uninstall."""
        result = _run_cli("opencode", "--help")
        assert result.returncode == 0
        out = result.stdout
        assert "install" in out
        assert "uninstall" in out

    def test_install_help_shows_flags(self) -> None:
        """``deeprefine opencode install --help`` shows --project and --user."""
        result = _run_cli("opencode", "install", "--help")
        assert result.returncode == 0
        out = result.stdout
        assert "--project" in out, f"missing --project flag in help: {out}"
        assert "--user" in out, f"missing --user flag in help: {out}"

    def test_uninstall_help_shows_flags(self) -> None:
        """``deeprefine opencode uninstall --help`` shows --project and --user."""
        result = _run_cli("opencode", "uninstall", "--help")
        assert result.returncode == 0
        out = result.stdout
        assert "--project" in out
        assert "--user" in out
