"""Transactional Graphify wiki refresh for ``deeprefine apply``.

The Graphify wiki is a derived view of ``graphify-out/graph.json``.  Updating
only the graph leaves the existing Markdown wiki stale.  This module stages a
refined graph and its regenerated wiki together, then commits both with
rollback on ordinary filesystem/process failures.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Hashable, Sequence

from deeprefine_skill.agent_graph import apply_refinement_text


class WikiRefreshError(RuntimeError):
    """Raised when Graphify cannot regenerate a valid staged wiki."""


@dataclass(frozen=True)
class WikiRefreshResult:
    """Result of a successful graph + wiki transaction."""

    changes: list[str]
    wiki_dir: Path
    command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""


def _graphify_command(executable: str | None = None) -> list[str]:
    """Resolve Graphify without invoking a shell.

    ``executable`` is primarily useful for tests and custom installations.
    Otherwise prefer the console script and fall back to ``python -m graphify``
    when Graphify is installed in the current Python environment but its script
    directory is not on ``PATH``.
    """
    if executable:
        return [executable]

    found = shutil.which("graphify")
    if found:
        return [found]

    try:
        import importlib.util

        if importlib.util.find_spec("graphify") is not None:
            return [sys.executable, "-m", "graphify"]
    except (ImportError, AttributeError, ValueError):
        pass

    raise WikiRefreshError(
        "Graphify CLI was not found. Install or upgrade it first, for example: "
        "`pip install -U graphifyy` (the package has two y's; the command is "
        "`graphify`)."
    )


def _community_map(graph_data: dict[str, Any]) -> dict[str, list[str]]:
    """Build exact community membership from the staged graph itself."""
    communities: dict[str, list[str]] = {}
    for node in graph_data.get("nodes", []):
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        raw_community = node.get("community")
        if raw_community is None:
            continue
        try:
            key = str(int(raw_community))
        except (TypeError, ValueError) as exc:
            raise WikiRefreshError(
                "Graphify community identifiers must be integer-like; "
                f"node {node['id']!r} has community {raw_community!r}."
            ) from exc
        communities.setdefault(key, []).append(str(node["id"]))
    return communities


def _stage_graphify_sidecars(source_out: Path, stage_out: Path, graph_data: dict[str, Any]) -> None:
    """Create sidecars that make the staged wiki follow the staged graph.

    An existing ``.graphify_analysis.json`` may describe the *old* graph.  We
    therefore regenerate its community membership from node attributes rather
    than copying stale membership or metrics.  God nodes and cohesion are
    intentionally omitted so Graphify derives Wiki content from the staged graph.
    """
    communities = _community_map(graph_data)
    if not communities:
        raise WikiRefreshError(
            "The refined graph has no node community metadata, so a reliable "
            "Wiki cannot be generated. Run `graphify cluster-only .` first."
        )

    analysis: dict[str, Any] = {"communities": communities}

    (stage_out / ".graphify_analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    labels = source_out / ".graphify_labels.json"
    if labels.is_file():
        shutil.copy2(labels, stage_out / labels.name)


def _links_key(graph_data: dict[str, Any]) -> str:
    return "links" if "links" in graph_data else "edges"


def _edge_identity(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(edge.get("source")),
        str(edge.get("target")),
        str(edge.get("relation", "")),
    )


def _endpoint_key(
    edge: dict[str, Any], *, directed: bool
) -> tuple[Hashable, Hashable]:
    source = str(edge.get("source"))
    target = str(edge.get("target"))
    if directed:
        return source, target
    return tuple(sorted((source, target)))


def _inserted_edges(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return only link records newly introduced by this refinement."""
    links_key = _links_key(after)
    before_counts: dict[tuple[str, str, str], int] = {}
    for edge in before.get(_links_key(before), []):
        if isinstance(edge, dict):
            identity = _edge_identity(edge)
            before_counts[identity] = before_counts.get(identity, 0) + 1

    inserted: list[dict[str, Any]] = []
    for edge in after.get(links_key, []):
        if not isinstance(edge, dict):
            continue
        identity = _edge_identity(edge)
        remaining = before_counts.get(identity, 0)
        if remaining:
            before_counts[identity] = remaining - 1
        else:
            inserted.append(edge)
    return inserted


def _find_parallel_endpoint_conflicts(
    before: dict[str, Any], after: dict[str, Any]
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Find newly inserted edges whose endpoints already had a relation.

    Graphify 0.9.12 can store parallel links, but its Wiki renderer currently
    consults only the first edge for an endpoint pair.  Blocking only newly
    introduced endpoint collisions avoids penalizing historical graph issues.
    """
    directed = bool(after.get("directed", before.get("directed", True)))
    occupied_by_endpoints: dict[tuple[Hashable, Hashable], list[dict[str, Any]]] = {}
    for edge in before.get(_links_key(before), []):
        if not isinstance(edge, dict):
            continue
        occupied_by_endpoints.setdefault(
            _endpoint_key(edge, directed=directed), []
        ).append(edge)

    conflicts: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for edge in _inserted_edges(before, after):
        endpoints = _endpoint_key(edge, directed=directed)
        occupied = occupied_by_endpoints.get(endpoints)
        if occupied:
            conflicts.append((edge, occupied))
        occupied_by_endpoints.setdefault(endpoints, []).append(edge)
    return conflicts


def _format_edge(edge: dict[str, Any]) -> str:
    return (
        f"{edge.get('source')!r} -[{edge.get('relation', '')}]-> "
        f"{edge.get('target')!r}"
    )


def _assert_wiki_export_can_represent_refinement(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    conflicts = _find_parallel_endpoint_conflicts(before, after)
    if not conflicts:
        return

    lines = [
        "Graphify Wiki refresh aborted: the current Graphify Wiki exporter does "
        "not support complete display of parallel relations for the same endpoint "
        "pair.",
        "The staged refinement introduced edge(s) whose endpoints already had "
        "other relation(s) in graph.json, so exporting now would make graph.json "
        "and the Wiki semantically inconsistent.",
    ]
    for inserted, existing_edges in conflicts[:5]:
        lines.append(f"New edge: {_format_edge(inserted)}")
        existing_preview = ", ".join(_format_edge(edge) for edge in existing_edges[:3])
        lines.append(f"Existing edge(s) on same endpoints: {existing_preview}")
    if len(conflicts) > 5:
        lines.append(f"... and {len(conflicts) - 5} more conflicting new edge(s).")
    lines.append(
        "graph.json and the existing Wiki were left unchanged. DeepRefine will "
        "not delete, overwrite, or merge existing relations automatically."
    )
    raise WikiRefreshError("\n".join(lines))


def _run_wiki_export(
    *,
    command_prefix: Sequence[str],
    graph_path: Path,
    project_root: Path,
    stage_out: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        *command_prefix,
        "export",
        "wiki",
        "--graph",
        str(graph_path),
    ]
    env = os.environ.copy()
    # Graphify uses GRAPHIFY_OUT to locate its analysis sidecar.  Pointing it at
    # the staging directory prevents it from reading stale production metadata.
    env["GRAPHIFY_OUT"] = str(stage_out)
    return subprocess.run(
        command,
        cwd=str(project_root),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _commit_graph_and_wiki(
    *,
    staged_graph: Path,
    staged_wiki: Path,
    graph_path: Path,
    wiki_dir: Path,
    transaction_root: Path,
) -> None:
    """Replace graph and wiki, rolling both back if an operation fails."""
    old_graph = transaction_root / "previous-graph.json"
    old_wiki = transaction_root / "previous-wiki"
    shutil.copy2(graph_path, old_graph)

    graph_replaced = False
    old_wiki_moved = False
    new_wiki_installed = False
    try:
        os.replace(staged_graph, graph_path)
        graph_replaced = True

        if wiki_dir.exists():
            os.replace(wiki_dir, old_wiki)
            old_wiki_moved = True

        os.replace(staged_wiki, wiki_dir)
        new_wiki_installed = True
    except Exception:
        # Remove a partially installed new wiki before restoring the old one.
        if new_wiki_installed and wiki_dir.exists():
            shutil.rmtree(wiki_dir, ignore_errors=True)
        if old_wiki_moved and old_wiki.exists() and not wiki_dir.exists():
            os.replace(old_wiki, wiki_dir)
        if graph_replaced and old_graph.exists():
            os.replace(old_graph, graph_path)
        raise


def apply_refinement_with_wiki_refresh(
    *,
    graph_path: Path,
    refinement_text: str,
    project_root: Path,
    graphify_executable: str | None = None,
) -> WikiRefreshResult:
    """Stage, validate, and commit a refined graph together with its Wiki.

    The production graph and Wiki are not changed unless Graphify exits
    successfully and creates ``wiki/index.md`` from the staged graph.
    """
    graph_path = graph_path.resolve()
    project_root = project_root.resolve()
    graphify_out = graph_path.parent
    wiki_dir = graphify_out / "wiki"
    command_prefix = _graphify_command(graphify_executable)

    transaction_parent = graphify_out / ".deeprefine"
    transaction_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="wiki-refresh-", dir=transaction_parent
    ) as tmp:
        transaction_root = Path(tmp)
        stage_out = transaction_root / "graphify-out"
        stage_out.mkdir(parents=True)
        staged_graph = stage_out / "graph.json"
        shutil.copy2(graph_path, staged_graph)

        original_graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
        changes = apply_refinement_text(staged_graph, refinement_text)
        graph_data = json.loads(staged_graph.read_text(encoding="utf-8"))
        _assert_wiki_export_can_represent_refinement(original_graph_data, graph_data)
        _stage_graphify_sidecars(graphify_out, stage_out, graph_data)

        completed = _run_wiki_export(
            command_prefix=command_prefix,
            graph_path=staged_graph,
            project_root=project_root,
            stage_out=stage_out,
        )
        command = (
            *command_prefix,
            "export",
            "wiki",
            "--graph",
            str(staged_graph),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise WikiRefreshError(
                "Graphify Wiki refresh failed; graph.json and the existing Wiki "
                f"were left unchanged. Command: {' '.join(command)}\n{detail}"
            )

        staged_wiki = stage_out / "wiki"
        index_path = staged_wiki / "index.md"
        if not index_path.is_file():
            raise WikiRefreshError(
                "Graphify exited successfully but did not create wiki/index.md; "
                "graph.json and the existing Wiki were left unchanged."
            )

        _commit_graph_and_wiki(
            staged_graph=staged_graph,
            staged_wiki=staged_wiki,
            graph_path=graph_path,
            wiki_dir=wiki_dir,
            transaction_root=transaction_root,
        )

    return WikiRefreshResult(
        changes=changes,
        wiki_dir=wiki_dir,
        command=tuple(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
