"""Incremental wiki update for ``deeprefine apply``.

Unlike ``wiki_refresh.py`` which regenerates the entire wiki via graphify,
this module applies refinement actions as incremental edits to wiki
markdown files — preserving all human-written content and only touching
the specific links or titles that changed.  Supports both ``[[wikilinks]]``
(Obsidian, Logseq, Roam) and ``[text](url)`` markdown links (GitHub Wiki).

Action → edit mapping::

    insert_edge("A", "links_to", "B")  →  append link to B from A's file
    delete_edge("A", "links_to", "B")  →  remove link to B from A's file
    replace_node("A", "New Title")     →  update ``# Title`` in A's file

The link syntax used for write-back matches the original file's convention
(via the ``link_format`` field on each graph node).

Operations are transactional: files are backed up before editing and
rolled back if any step fails.  Idempotent — re-applying the same
refinement produces no duplicate edits.

Follows the same ``WikiRefreshResult`` pattern as ``wiki_refresh.py``
so the CLI can dispatch to either backend transparently.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from deeprefine_skill.agent_graph import _parse_action_string, parse_refinement_block


# ---------------------------------------------------------------------------
# Exceptions & result types
# ---------------------------------------------------------------------------


class WikiUpdateError(RuntimeError):
    """Raised when incremental wiki update cannot complete safely.

    The original files are left unchanged (rolled back if any edits were
    already applied).
    """


@dataclass(frozen=True)
class WikiUpdateResult:
    """Result of a successful incremental Obsidian wiki refresh.

    Attributes:
        changes: Human-readable descriptions of each edit applied.
        updated_files: Absolute paths of .md files that were modified.
    """

    changes: list[str]
    updated_files: list[Path]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_node(nodes: list[dict], name: str) -> dict | None:
    """Case-insensitive node lookup by *label* or *id*."""
    target = name.strip().casefold()
    for n in nodes:
        if n.get("label", "").casefold() == target:
            return n
        if n.get("id", "").casefold() == target:
            return n
    return None


def _wikilink_re(label: str) -> re.Pattern:
    """Build a regex that matches ``[[label]]`` with optional alias / heading."""
    return re.compile(
        r"\[\["
        + re.escape(label)
        + r"(?:\|[^\]]*)?(?:\#[^\]]*)?"
        + r"\]\]"
    )


def _has_wikilink(text: str, label: str) -> bool:
    """Return True if *text* contains ``[[label]]`` (any variant)."""
    return bool(_wikilink_re(label).search(text))


def _append_wikilink(md_path: Path, target_label: str) -> str | None:
    """Append ``[[target_label]]`` to the end of *md_path*.

    Returns a change description, or ``None`` if the link is already present
    (idempotent).
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    if _has_wikilink(text, target_label):
        return None  # already present — idempotent

    # Append at end of file with a blank-line separator
    new_text = text.rstrip() + f"\n\n[[{target_label}]]\n"
    md_path.write_text(new_text, encoding="utf-8")
    return f"Added [[{target_label}]] to {md_path.name}"


def _remove_wikilink(md_path: Path, target_label: str) -> str | None:
    """Remove *all* occurrences of ``[[target_label]]`` from *md_path*.

    Returns a change description, or ``None`` if no matching link was found.
    Handles Obsidian variants: ``|alias``, ``#heading``, combinations.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    if not _has_wikilink(text, target_label):
        return None

    # Remove the wikilink line — the pattern matches a line that is
    # *only* the wikilink (list-item style) or an inline wikilink
    # followed by optional newline cleanup.
    pattern = _wikilink_re(target_label)
    new_text, count = pattern.subn("", text)

    if count == 0:
        return None

    # Clean up: collapse 3+ consecutive newlines → 2, remove trailing
    # whitespace-only lines
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    new_text = new_text.rstrip() + "\n"

    md_path.write_text(new_text, encoding="utf-8")
    return f"Removed [[{target_label}]] from {md_path.name}"


def _replace_title(md_path: Path, old_label: str, new_label: str) -> str | None:
    """Replace the first ``# old_label`` heading with ``# new_label``.

    Returns a change description, or ``None`` if the old title is not found.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    # Match ``# Old Title`` at the start of a line (first occurrence only)
    escaped = re.escape(old_label)
    pattern = re.compile(r"^#\s+" + escaped + r"\s*$", re.MULTILINE)
    new_text, count = pattern.subn(f"# {new_label}", text, count=1)

    if count == 0:
        return None

    md_path.write_text(new_text, encoding="utf-8")
    return f"Renamed title '{old_label}' → '{new_label}' in {md_path.name}"


# ---------------------------------------------------------------------------
# Markdown-link write-back helpers  ([text](url) — GitHub Wiki etc.)
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convert arbitrary text to a kebab-case identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "page"


def _mdlink_re(display_text: str) -> re.Pattern:
    """Build a regex that matches ``[display_text](<any url>)``."""
    return re.compile(
        r"\["
        + re.escape(display_text)
        + r"\]\([^)]+\)"
    )


def _has_mdlink(text: str, display_text: str) -> bool:
    """Return True if *text* contains ``[display_text](...)``."""
    return bool(_mdlink_re(display_text).search(text))


def _append_mdlink(md_path: Path, target_label: str) -> str | None:
    """Append ``[target_label](target-slug.md)`` to the end of *md_path*.

    Returns a change description, or ``None`` if the link is already present
    (idempotent).
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    if _has_mdlink(text, target_label):
        return None

    target_url = f"{_slug(target_label)}.md"
    new_text = text.rstrip() + f"\n\n[{target_label}]({target_url})\n"
    md_path.write_text(new_text, encoding="utf-8")
    return f"Added [{target_label}]({target_url}) to {md_path.name}"


def _remove_mdlink(md_path: Path, target_label: str) -> str | None:
    """Remove *all* occurrences of ``[target_label](...)`` from *md_path*.

    Returns a change description, or ``None`` if no matching link was found.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    if not _has_mdlink(text, target_label):
        return None

    pattern = _mdlink_re(target_label)
    new_text, count = pattern.subn("", text)

    if count == 0:
        return None

    # Clean up: collapse 3+ consecutive newlines → 2
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    new_text = new_text.rstrip() + "\n"

    md_path.write_text(new_text, encoding="utf-8")
    return f"Removed [{target_label}](...md) from {md_path.name}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_refinement_with_wiki_update(
    graph_path: Path,
    refinement_text: str,
) -> WikiUpdateResult:
    """Apply refinement actions as incremental edits to wiki files.

    Reads *graph_path* to resolve node labels → ``page_path`` values,
    then applies each action from *refinement_text* to the corresponding
    markdown file.

    The graph.json itself is **not** modified — use
    :func:`deeprefine_skill.agent_graph.apply_refinement_text` first,
    then call this function to sync the wiki.

    Transactional behaviour:
        - All target files are backed up (in-memory) before any edit.
        - Edits are applied one-by-one; if *any* step raises, **all**
          modified files are restored to their original content.
        - Idempotent: re-applying the same refinement is a no-op for
          links that already exist / titles already updated.

    Args:
        graph_path: Path to ``graph.json`` (must contain wiki nodes with
            ``page_path`` fields).
        refinement_text: A ``<refinement>…</refinement>`` XML block.

    Returns:
        :class:`WikiUpdateResult` with change descriptions and the
        list of modified files.

    Raises:
        WikiUpdateError: If a referenced node or page file is missing,
            or if a file write fails (original content is restored).
    """
    graph_path = graph_path.resolve()
    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes: list[dict] = graph_data.get("nodes", [])
    actions = parse_refinement_block(refinement_text)

    # ------------------------------------------------------------------
    # Phase 1 — Plan: map actions → (file, edit_description, edit_fn)
    # ------------------------------------------------------------------
    EditFn = callable  # () -> str | None

    planned: list[tuple[Path, str, EditFn]] = []
    touched_files: set[Path] = set()

    for action_str in actions:
        fn, args = _parse_action_string(action_str)

        if fn == "insert_edge":
            sub_label, rel, obj_label = args[0], args[1], args[2]
            if rel.strip().casefold() != "links_to":
                continue

            sub_node = _find_node(nodes, sub_label)
            if sub_node is None:
                raise WikiUpdateError(
                    f"Source node not found in graph: {sub_label!r}"
                )
            md_path = Path(sub_node.get("page_path", ""))
            if not md_path.is_file():
                raise WikiUpdateError(
                    f"Wiki page not found for node {sub_label!r}: {md_path}"
                )

            # Use the target node's label for the link text (human-readable),
            # falling back to the argument string for dangling targets.
            obj_node = _find_node(nodes, obj_label)
            link_text = obj_node["label"] if obj_node else obj_label

            # Dispatch to the correct write-back function based on the
            # source file's original link convention.
            link_format = sub_node.get("link_format", "wikilink")

            if link_format == "mdlink":
                planned.append((
                    md_path,
                    f"insert [{link_text}](...) → {md_path.name}",
                    lambda p=md_path, lt=link_text: _append_mdlink(p, lt),
                ))
            else:
                planned.append((
                    md_path,
                    f"insert [[{link_text}]] → {md_path.name}",
                    lambda p=md_path, lt=link_text: _append_wikilink(p, lt),
                ))
            touched_files.add(md_path)

        elif fn == "delete_edge":
            sub_label, rel, obj_label = args[0], args[1], args[2]
            if rel.strip().casefold() != "links_to":
                continue

            sub_node = _find_node(nodes, sub_label)
            if sub_node is None:
                raise WikiUpdateError(
                    f"Source node not found in graph: {sub_label!r}"
                )
            md_path = Path(sub_node.get("page_path", ""))
            if not md_path.is_file():
                raise WikiUpdateError(
                    f"Wiki page not found for node {sub_label!r}: {md_path}"
                )

            obj_node = _find_node(nodes, obj_label)
            link_text = obj_node["label"] if obj_node else obj_label

            # Dispatch to the correct write-back function based on the
            # source file's original link convention.
            link_format = sub_node.get("link_format", "wikilink")

            if link_format == "mdlink":
                planned.append((
                    md_path,
                    f"delete [{link_text}](...) from {md_path.name}",
                    lambda p=md_path, lt=link_text: _remove_mdlink(p, lt),
                ))
            else:
                planned.append((
                    md_path,
                    f"delete [[{link_text}]] from {md_path.name}",
                    lambda p=md_path, lt=link_text: _remove_wikilink(p, lt),
                ))
            touched_files.add(md_path)

        elif fn == "replace_node":
            old_label, new_label = args[0], args[1]

            node = _find_node(nodes, old_label)
            if node is None:
                raise WikiUpdateError(
                    f"Node not found in graph: {old_label!r}"
                )
            md_path = Path(node.get("page_path", ""))
            if not md_path.is_file():
                raise WikiUpdateError(
                    f"Wiki page not found for node {old_label!r}: {md_path}"
                )

            # Use the node's actual label (human-readable title) for
            # the markdown heading search, not the action argument
            # which may be a page ID like "machine-learning".
            actual_title = node["label"]

            planned.append((
                md_path,
                f"rename '{actual_title}' → '{new_label}' in {md_path.name}",
                lambda p=md_path, o=actual_title, n=new_label: _replace_title(p, o, n),
            ))
            touched_files.add(md_path)

        # Unknown action types are silently skipped — they may be handled
        # by other refresh backends.

    if not planned:
        return WikiUpdateResult(changes=[], updated_files=[])

    # ------------------------------------------------------------------
    # Phase 2 — Execute: backup → apply → rollback on failure
    # ------------------------------------------------------------------
    backups: dict[Path, str] = {}
    changes: list[str] = []

    try:
        for f in touched_files:
            backups[f] = f.read_text(encoding="utf-8", errors="ignore")

        for md_path, _desc, edit_fn in planned:
            result = edit_fn()
            if result:
                changes.append(result)

    except Exception:
        # Restore every file we backed up
        for f, original in backups.items():
            try:
                f.write_text(original, encoding="utf-8")
            except OSError:
                pass
        raise WikiUpdateError(
            f"Refresh failed after {len(changes)} change(s); "
            f"all {len(backups)} file(s) restored to original content."
        )

    return WikiUpdateResult(
        changes=changes,
        updated_files=sorted(touched_files),
    )
