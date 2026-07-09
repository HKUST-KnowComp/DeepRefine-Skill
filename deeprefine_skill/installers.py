"""Installers for agent-platform skill files (Cursor, Copilot CLI, Gemini CLI, OpenCode).

Each platform has a source SKILL.md variant (SKILL.md for Cursor,
SKILL_COPILOT.md for Copilot CLI, gemini_extension/ for Gemini CLI,
SKILL_OPENCODE.md for OpenCode) bundled in the wheel or found at the
repo root during editable installs. The install/remove functions copy
the appropriate variant into the platform-specific directory.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_SKILL_MD_NAME = "SKILL.md"
_SKILL_COPILOT_MD_NAME = "SKILL_COPILOT.md"
_SKILL_OPENCODE_MD_NAME = "SKILL_OPENCODE.md"
_CODEX_SKILL_DIR = "codex_skill"
_CODEX_AGENTS_DIR = "agents"
_CODEX_REFERENCES_DIR = "references"
_LEGACY_CODEX_AGENT_LOOP_REF_NAME = "deeprefine-agent-loop.md"
_OPENAI_YAML_NAME = "openai.yaml"
_GEMINI_EXTENSION_NAME = "deeprefine-skill"
_OPENCODE_COMMANDS_DIR = "commands"

# ---------------------------------------------------------------------------
# Source-file resolution
# ---------------------------------------------------------------------------


def _resolve_skill_source(filename: str) -> Path:
    """Return *filename* from the package directory, or fall back to repo root."""
    bundled = Path(__file__).resolve().parent / filename
    if bundled.is_file():
        return bundled
    repo_root = Path(__file__).resolve().parents[1]
    fallback = repo_root / filename
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        f"Missing {filename} (expected next to deeprefine_skill/ or repo root)."
    )


def skill_md_path() -> Path:
    """Return the path to the Cursor SKILL.md source."""
    return _resolve_skill_source(_SKILL_MD_NAME)


def skill_md_path_copilot() -> Path:
    """Return the path to the Copilot CLI SKILL_COPILOT.md source."""
    return _resolve_skill_source(_SKILL_COPILOT_MD_NAME)


def skill_md_path_codex() -> Path:
    """Return the path to the Codex SKILL.md source."""
    return codex_skill_template_path() / _SKILL_MD_NAME


def codex_openai_yaml_path() -> Path:
    """Return the Codex agents/openai.yaml metadata source."""
    return codex_skill_template_path() / _CODEX_AGENTS_DIR / _OPENAI_YAML_NAME


def codex_references_path() -> Path:
    """Return the Codex references template directory."""
    refs = codex_skill_template_path() / _CODEX_REFERENCES_DIR
    if refs.is_dir():
        return refs
    raise FileNotFoundError(
        "Missing Codex references template (expected under "
        "deeprefine_skill/codex_skill/references/)."
    )


def codex_skill_template_path() -> Path:
    """Return the Codex skill template directory."""
    bundled = Path(__file__).resolve().parent / _CODEX_SKILL_DIR
    if (bundled / _SKILL_MD_NAME).is_file():
        return bundled
    repo_root = Path(__file__).resolve().parents[1]
    fallback = repo_root / "deeprefine_skill" / _CODEX_SKILL_DIR
    if (fallback / _SKILL_MD_NAME).is_file():
        return fallback
    raise FileNotFoundError(
        "Missing Codex skill template (expected under "
        "deeprefine_skill/codex_skill/)."
    )


def gemini_extension_path(*, prefer_repo: bool = True) -> Path:
    """Return a Gemini CLI extension root.

    In editable/source checkouts, the repository root is preferred because
    it can be linked with ``gemini extensions link .``.  In wheels, use the
    bundled template under ``deeprefine_skill/gemini_extension/``.
    """
    repo_root = Path(__file__).resolve().parents[1]
    if prefer_repo and (repo_root / "gemini-extension.json").is_file():
        return repo_root
    bundled = Path(__file__).resolve().parent / "gemini_extension"
    if (bundled / "gemini-extension.json").is_file():
        return bundled
    if (repo_root / "gemini-extension.json").is_file():
        return repo_root
    raise FileNotFoundError(
        "Missing Gemini extension template. Expected either repo root "
        "gemini-extension.json or deeprefine_skill/gemini_extension/."
    )


def _copy_tree_clean(src: Path, dest: Path) -> None:
    """Recursively copy *src* to *dest*, removing *dest* first if it exists."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


def install_cursor_skill(*, project: bool) -> Path:
    """Install the Cursor skill into ``.cursor/skills/deeprefine/``.

    Parameters
    ----------
    project : bool
        If *True*, install under the current working directory
        (``.cursor/skills/deeprefine/``).  If *False*, install under
        ``~/.cursor/skills/deeprefine/`` (user-wide).

    Returns
    -------
    Path
        Destination path of the installed ``SKILL.md``.
    """
    src = skill_md_path()
    if project:
        dest_dir = Path.cwd() / ".cursor" / "skills" / "deeprefine"
    else:
        dest_dir = Path.home() / ".cursor" / "skills" / "deeprefine"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / _SKILL_MD_NAME)
    return dest_dir / _SKILL_MD_NAME


def uninstall_cursor_skill(*, project: bool) -> bool:
    """Remove a previously installed Cursor skill.

    Returns
    -------
    bool
        *True* if a file was removed, *False* if nothing was installed.
    """
    if project:
        dest = Path.cwd() / ".cursor" / "skills" / "deeprefine" / _SKILL_MD_NAME
    else:
        dest = Path.home() / ".cursor" / "skills" / "deeprefine" / _SKILL_MD_NAME
    if dest.is_file():
        dest.unlink()
        for parent in [dest.parent, dest.parent.parent]:
            try:
                parent.rmdir()
            except OSError:
                pass
        return True
    return False


# ---------------------------------------------------------------------------
# Copilot CLI
# ---------------------------------------------------------------------------


def install_copilot_skill(*, project: bool) -> Path:
    """Install the Copilot CLI skill into ``.github/skills/deeprefine/``.

    Parameters
    ----------
    project : bool
        If *True*, install under the current working directory
        (``.github/skills/deeprefine/``).  If *False*, install under
        ``~/.copilot/skills/deeprefine/`` (user-wide).

    Returns
    -------
    Path
        Destination path of the installed ``SKILL.md``.
    """
    src = skill_md_path_copilot()
    if project:
        dest_dir = Path.cwd() / ".github" / "skills" / "deeprefine"
    else:
        dest_dir = Path.home() / ".copilot" / "skills" / "deeprefine"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / _SKILL_MD_NAME)
    return dest_dir / _SKILL_MD_NAME


def uninstall_copilot_skill(*, project: bool) -> bool:
    """Remove a previously installed Copilot CLI skill.

    Returns
    -------
    bool
        *True* if a file was removed, *False* if nothing was installed.
    """
    if project:
        dest = Path.cwd() / ".github" / "skills" / "deeprefine" / _SKILL_MD_NAME
    else:
        dest = Path.home() / ".copilot" / "skills" / "deeprefine" / _SKILL_MD_NAME
    if dest.is_file():
        dest.unlink()
        for parent in [dest.parent, dest.parent.parent]:
            try:
                parent.rmdir()
            except OSError:
                pass
        return True
    return False


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


def install_codex_skill(*, project: bool) -> Path:
    """Install the Codex skill into ``.agents/skills/deeprefine/``.

    Parameters
    ----------
    project : bool
        If *True*, install under the current working directory
        (``.agents/skills/deeprefine/``). If *False*, install under
        ``~/.codex/skills/deeprefine/`` (user-wide).

    Returns
    -------
    Path
        Destination path of the installed ``SKILL.md``.
    """
    src_skill = skill_md_path_codex()
    src_references = codex_references_path()
    src_metadata = codex_openai_yaml_path()
    if project:
        dest_dir = Path.cwd() / ".agents" / "skills" / "deeprefine"
    else:
        dest_dir = Path.home() / ".codex" / "skills" / "deeprefine"
    metadata_dir = dest_dir / "agents"
    references_dir = dest_dir / _CODEX_REFERENCES_DIR
    metadata_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_skill, dest_dir / _SKILL_MD_NAME)
    shutil.copy2(src_metadata, metadata_dir / _OPENAI_YAML_NAME)
    legacy_ref = references_dir / _LEGACY_CODEX_AGENT_LOOP_REF_NAME
    if legacy_ref.is_file():
        legacy_ref.unlink()
    for ref in src_references.glob("*.md"):
        shutil.copy2(ref, references_dir / ref.name)
    return dest_dir / _SKILL_MD_NAME


def uninstall_codex_skill(*, project: bool) -> bool:
    """Remove a previously installed Codex skill."""
    if project:
        dest_dir = Path.cwd() / ".agents" / "skills" / "deeprefine"
    else:
        dest_dir = Path.home() / ".codex" / "skills" / "deeprefine"

    removed = False
    for dest in [
        dest_dir / _SKILL_MD_NAME,
        dest_dir / "agents" / _OPENAI_YAML_NAME,
        dest_dir / _CODEX_REFERENCES_DIR / "reafiner-workflow.md",
        dest_dir / _CODEX_REFERENCES_DIR / "llm-prompts.md",
        dest_dir / _CODEX_REFERENCES_DIR / "trace-and-commands.md",
        dest_dir / _CODEX_REFERENCES_DIR / _LEGACY_CODEX_AGENT_LOOP_REF_NAME,
    ]:
        if dest.is_file():
            dest.unlink()
            removed = True

    for parent in [
        dest_dir / "agents",
        dest_dir / _CODEX_REFERENCES_DIR,
        dest_dir,
        dest_dir.parent,
    ]:
        try:
            parent.rmdir()
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Gemini CLI
# ---------------------------------------------------------------------------


def _gemini_executable() -> str:
    """Return the path to the ``gemini`` CLI, or raise if not installed."""
    exe = shutil.which("gemini")
    if not exe:
        raise FileNotFoundError(
            "Gemini CLI executable `gemini` was not found. Install it first with:\n"
            "  npm install -g @google/gemini-cli"
        )
    return exe


def _run_gemini_extensions(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``gemini extensions <args>`` and return the completed process."""
    exe = _gemini_executable()
    return subprocess.run([exe, "extensions", *args], text=True)


def copy_gemini_extension(target_dir: Path | None = None) -> Path:
    """Manual fallback: copy extension files under ``~/.gemini/extensions``."""
    src = gemini_extension_path(prefer_repo=False)
    if target_dir is None:
        dest = Path.home() / ".gemini" / "extensions" / _GEMINI_EXTENSION_NAME
    else:
        dest = Path(target_dir).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree_clean(src, dest)
    return dest


def remove_copied_gemini_extension(target_dir: Path | None = None) -> bool:
    """Remove a manually copied Gemini extension directory.

    Returns
    -------
    bool
        *True* if the directory was removed, *False* if it did not exist.
    """
    if target_dir is None:
        dest = Path.home() / ".gemini" / "extensions" / _GEMINI_EXTENSION_NAME
    else:
        dest = Path(target_dir).expanduser().resolve()
    if dest.exists():
        shutil.rmtree(dest)
        return True
    return False


def link_gemini_extension(source: Path | None = None) -> Path:
    """Use Gemini CLI's official manager to link an extension directory.

    Parameters
    ----------
    source : Path or None
        Extension root to link.  Defaults to the repo root when available.

    Returns
    -------
    Path
        The linked source directory.
    """
    src = (source or gemini_extension_path(prefer_repo=True)).expanduser().resolve()
    if not (src / "gemini-extension.json").is_file():
        raise FileNotFoundError(f"Not a Gemini extension root: {src}")
    cp = _run_gemini_extensions(["link", str(src)])
    if cp.returncode != 0:
        raise RuntimeError(
            f"`gemini extensions link {src}` failed with exit code {cp.returncode}"
        )
    return src


def install_gemini_extension(
    source: Path | None = None, *, consent: bool = True
) -> Path:
    """Use Gemini CLI's official manager to install a copied extension.

    Parameters
    ----------
    source : Path or None
        Extension root to install.  Defaults to the bundled template.
    consent : bool
        If *True*, pass ``--consent`` to ``gemini extensions install``.

    Returns
    -------
    Path
        The installed source directory.
    """
    src = (source or gemini_extension_path(prefer_repo=False)).expanduser().resolve()
    if not (src / "gemini-extension.json").is_file():
        raise FileNotFoundError(f"Not a Gemini extension root: {src}")
    cmd = ["install", str(src)]
    if consent:
        cmd.append("--consent")
    cp = _run_gemini_extensions(cmd)
    if cp.returncode != 0:
        raise RuntimeError(
            f"`gemini extensions {' '.join(cmd)}` failed with exit code {cp.returncode}"
        )
    return src


def uninstall_gemini_extension(
    *, copy_only: bool = False, target_dir: Path | None = None
) -> bool:
    """Uninstall through Gemini CLI manager, or remove manual copied files.

    Returns
    -------
    bool
        *True* if the extension was removed, *False* otherwise.
    """
    if copy_only:
        return remove_copied_gemini_extension(target_dir)
    cp = _run_gemini_extensions(["uninstall", _GEMINI_EXTENSION_NAME])
    if cp.returncode == 0:
        return True
    # Also clean up the old manual-copy fallback if present.
    return remove_copied_gemini_extension(target_dir)


# ---------------------------------------------------------------------------
# OpenCode
# ---------------------------------------------------------------------------


def _opencode_skill_source() -> Path:
    """Return the path to the OpenCode SKILL_OPENCODE.md source."""
    return _resolve_skill_source(_SKILL_OPENCODE_MD_NAME)


def _opencode_commands_source_dir() -> Path:
    """Return the directory containing OpenCode command .md files."""
    bundled = Path(__file__).resolve().parent / _OPENCODE_COMMANDS_DIR / "opencode"
    if bundled.is_dir() and list(bundled.glob("*.md")):
        return bundled
    repo_root = Path(__file__).resolve().parents[1]
    fallback = repo_root / "deeprefine_skill" / _OPENCODE_COMMANDS_DIR / "opencode"
    if fallback.is_dir() and list(fallback.glob("*.md")):
        return fallback
    raise FileNotFoundError(
        "Missing OpenCode command templates (expected under "
        "deeprefine_skill/commands/opencode/)."
    )


def install_opencode_skill(*, project: bool) -> Path:
    """Install the OpenCode skill and commands.

    Copies:
    - ``SKILL_OPENCODE.md`` → ``.opencode/skills/deeprefine/SKILL.md``
    - ``commands/opencode/*.md`` → ``.opencode/commands/*.md``

    Parameters
    ----------
    project : bool
        If *True*, install under the current working directory
        (``.opencode/skills/deeprefine/``).  If *False*, install under
        ``~/.opencode/skills/deeprefine/`` (user-wide).

    Returns
    -------
    Path
        Destination path of the installed ``SKILL.md``.
    """
    src_skill = _opencode_skill_source()
    src_commands = _opencode_commands_source_dir()
    if project:
        dest_skill_dir = Path.cwd() / ".opencode" / "skills" / "deeprefine"
        dest_cmd_dir = Path.cwd() / ".opencode" / "commands"
    else:
        dest_skill_dir = Path.home() / ".claude" / "skills" / "deeprefine"
        dest_cmd_dir = Path.home() / ".opencode" / "commands"
    dest_skill_dir.mkdir(parents=True, exist_ok=True)
    dest_cmd_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_skill, dest_skill_dir / _SKILL_MD_NAME)
    for cmd in src_commands.glob("*.md"):
        shutil.copy2(cmd, dest_cmd_dir / cmd.name)
    return dest_skill_dir / _SKILL_MD_NAME


def uninstall_opencode_skill(*, project: bool) -> bool:
    """Remove a previously installed OpenCode skill and commands.

    Returns
    -------
    bool
        *True* if any file was removed, *False* if nothing was installed.
    """
    if project:
        dest_skill = Path.cwd() / ".opencode" / "skills" / "deeprefine" / _SKILL_MD_NAME
        dest_cmd_dir = Path.cwd() / ".opencode" / "commands"
    else:
        dest_skill = Path.home() / ".opencode" / "skills" / "deeprefine" / _SKILL_MD_NAME
        dest_cmd_dir = Path.home() / ".opencode" / "commands"
    removed = False
    if dest_skill.is_file():
        dest_skill.unlink()
        removed = True
    for cmd in dest_cmd_dir.glob("deeprefine*.md"):
        cmd.unlink()
        removed = True
    # Clean skill-tree parents: deeprefine/, skills/, .opencode/
    for parent in [dest_skill.parent, dest_skill.parent.parent, dest_skill.parent.parent.parent]:
        try:
            parent.rmdir()
        except OSError:
            pass
    # Clean commands/ if empty (only rmdir — never remove if other files exist)
    try:
        dest_cmd_dir.rmdir()
    except OSError:
        pass
    # Clean .opencode/ itself (may still fail if commands/ was non-empty)
    try:
        dest_skill.parent.parent.parent.rmdir()
    except OSError:
        pass
    return removed
