"""Stage 3 open/closed-book contract for Re-DocRED.

The paired experiment uses the same relation graph in both conditions.  Source
text is supplied only through DeepRefine's public ``original_chunk`` argument,
which is also the path used by the upstream research benchmarks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol


ContextMode = Literal["open", "closed"]
DEFAULT_MAX_CONTEXT_CHARS = 12_000
CONTEXT_SELECTION_RULE = "suite.case.source_files[0] -> corpus/<source_file>"
CONTEXT_SERIALIZATION_RULE = (
    "Re-DocRED sentence tokens joined by one space; sentences joined by two newlines"
)


class Refiner(Protocol):
    """Small part of the DeepRefine interface needed by Stage 3."""

    def refine(
        self,
        *,
        query: str,
        original_chunk: str | None,
    ) -> Any: ...


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def select_source_text(
    source_text: str,
    *,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> tuple[str, dict[str, Any]]:
    """Apply the frozen Stage 3 context selection and prefix budget."""

    if max_context_chars <= 0:
        raise ValueError("max_context_chars must be positive")
    normalized = source_text.strip()
    if not normalized:
        raise ValueError("Stage 3 source text must not be empty")
    selected = normalized[:max_context_chars]
    return selected, {
        "selection_rule": CONTEXT_SELECTION_RULE,
        "serialization_rule": CONTEXT_SERIALIZATION_RULE,
        "truncation": {
            "unit": "unicode_codepoints",
            "strategy": "prefix",
            "max_chars": max_context_chars,
            "input_chars": len(normalized),
            "selected_chars": len(selected),
            "truncated": len(selected) < len(normalized),
        },
        "input_sha256": _text_sha256(normalized),
        "selected_sha256": _text_sha256(selected),
    }


def relation_graph_without_passages(
    graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy with passage nodes and their incident links removed.

    Stage 3 must not depend on DeepRefine's passage fallback.  Removing passage
    content from the common graph also prevents a future fallback fix from
    silently turning the closed-book condition into open-book.
    """

    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise ValueError("graph must contain list-valued 'nodes' and 'links'")

    passage_ids: set[Any] = set()
    for node in nodes:
        if not isinstance(node, Mapping) or "id" not in node:
            raise ValueError("every graph node must be an object with an 'id'")
        if str(node.get("type", "")).strip().lower() == "passage":
            passage_ids.add(node["id"])

    prepared = copy.deepcopy(dict(graph))
    prepared["nodes"] = [
        copy.deepcopy(node) for node in nodes if node["id"] not in passage_ids
    ]
    prepared["links"] = [
        copy.deepcopy(link)
        for link in links
        if isinstance(link, Mapping)
        and link.get("source") not in passage_ids
        and link.get("target") not in passage_ids
    ]

    if any(
        str(node.get("type", "")).strip().lower() == "passage"
        for node in prepared["nodes"]
    ):
        raise AssertionError("passage node remained in the prepared Stage 3 graph")
    return prepared


def prepare_paired_graphs(
    graph: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build byte-equivalent open/closed graph payloads and their content hash."""

    common = relation_graph_without_passages(graph)
    open_graph = copy.deepcopy(common)
    closed_graph = copy.deepcopy(common)
    open_hash = _canonical_sha256(open_graph)
    closed_hash = _canonical_sha256(closed_graph)
    if open_hash != closed_hash:
        raise AssertionError("open and closed Stage 3 graphs differ")
    return open_graph, closed_graph, open_hash


def build_refine_kwargs(
    *,
    query: str,
    context_mode: ContextMode,
    source_text: str,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> dict[str, str | None]:
    """Make the paired DeepRefine call, varying only ``original_chunk``."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Stage 3 query must not be empty")
    if context_mode not in ("open", "closed"):
        raise ValueError(f"unsupported Stage 3 context mode: {context_mode!r}")
    selected_source, _ = select_source_text(
        source_text,
        max_context_chars=max_context_chars,
    )

    return {
        "query": normalized_query,
        "original_chunk": selected_source if context_mode == "open" else None,
    }


def git_revision(repo: Path) -> dict[str, Any]:
    """Return the exact commit and dirty state without changing the repository."""

    resolved = repo.resolve()
    head = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(resolved), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"path": str(resolved), "commit": head, "dirty": bool(status.strip())}


def build_run_metadata(
    *,
    case_id: str,
    context_mode: ContextMode,
    source_file: str,
    source_text: str,
    graph_sha256: str,
    code_revisions: Mapping[str, Mapping[str, Any]],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> dict[str, Any]:
    """Build the reproducibility record stored beside every Stage 3 run."""

    selected, context = select_source_text(
        source_text,
        max_context_chars=max_context_chars,
    )
    if context_mode not in ("open", "closed"):
        raise ValueError(f"unsupported Stage 3 context mode: {context_mode!r}")
    return {
        "schema_version": 1,
        "study": "s3-redocred",
        "case_id": case_id,
        "context_mode": context_mode,
        "graph_sha256": graph_sha256,
        "context": {
            "dataset": "Re-DocRED",
            "source_file": source_file,
            **context,
            "passed_to_original_chunk": context_mode == "open",
            "original_chunk_chars": len(selected) if context_mode == "open" else 0,
        },
        "code_revisions": copy.deepcopy(dict(code_revisions)),
    }


def write_run_metadata(path: Path, metadata: Mapping[str, Any]) -> None:
    """Write one stable, human-readable Stage 3 metadata record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_stage3_query(
    refiner: Refiner,
    *,
    query: str,
    context_mode: ContextMode,
    source_text: str,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> Any:
    """Run one Stage 3 condition through the explicit context contract."""

    return refiner.refine(
        **build_refine_kwargs(
            query=query,
            context_mode=context_mode,
            source_text=source_text,
            max_context_chars=max_context_chars,
        )
    )
