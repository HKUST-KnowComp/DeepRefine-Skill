from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_graph import _parse_action_string, parse_refinement_block


AMBIGUOUS_LABELS = {
    "main",
    "main()",
    "run",
    "run()",
    "train",
    "train()",
    "test",
    "test()",
    "setup",
    "setup()",
}


@dataclass
class ActionReview:
    action: str
    confidence: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggested_replacement: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "suggested_replacement": self.suggested_replacement,
        }


def _label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "")


def _node_source(node: dict[str, Any]) -> str | None:
    src = node.get("source_file") or node.get("file_id") or node.get("source_url")
    return str(src) if src else None


def _all_node_names(node: dict[str, Any]) -> set[str]:
    names = {_label(node), str(node.get("id") or "")}
    names.update(str(a) for a in node.get("aliases") or [])
    return {n.strip() for n in names if n and n.strip()}


def _split_qualified_label(name: str) -> tuple[str | None, str]:
    if "::" not in name:
        return None, name
    src, label = name.rsplit("::", 1)
    return src.strip() or None, label.strip()


def _source_matches(node: dict[str, Any], src: str | None) -> bool:
    if not src:
        return True
    node_src = _node_source(node)
    if not node_src:
        return False
    node_src = node_src.replace("\\", "/").strip()
    src = src.replace("\\", "/").strip()
    return node_src == src or node_src.endswith("/" + src) or src.endswith("/" + node_src)


def _matching_nodes(nodes: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    query_src, query_label = _split_qualified_label(name.strip())
    target = query_label.casefold()
    return [
        n
        for n in nodes
        if _source_matches(n, query_src)
        and target in {x.casefold() for x in _all_node_names(n)}
    ]


def _function_tail(name: str) -> str | None:
    stripped = name.strip()
    if "::" in stripped:
        stripped = stripped.rsplit("::", 1)[-1]
    if stripped.endswith("()"):
        return stripped
    return None


def _candidate_qualified_nodes(nodes: list[dict[str, Any]], bare_name: str) -> list[dict[str, Any]]:
    tail = _function_tail(bare_name)
    if not tail:
        return []
    out: list[dict[str, Any]] = []
    for n in nodes:
        names = _all_node_names(n)
        if any(x.endswith(f"::{tail}") or x.endswith(f".{tail}") for x in names):
            out.append(n)
    return out


def _candidate_labels(candidates: list[dict[str, Any]]) -> list[str]:
    labels = sorted({_format_node(n) for n in candidates})
    return labels[:3]


def _links(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return list(raw.get("links") or raw.get("edges") or [])


def _edge_exists(
    raw: dict[str, Any],
    subject_nodes: list[dict[str, Any]],
    relation: str,
    object_nodes: list[dict[str, Any]],
) -> bool:
    subject_ids = {str(n.get("id")) for n in subject_nodes}
    object_ids = {str(n.get("id")) for n in object_nodes}
    for link in _links(raw):
        if (
            str(link.get("source")) in subject_ids
            and str(link.get("target")) in object_ids
            and str(link.get("relation") or link.get("label") or "") == relation
        ):
            return True
    return False


def _code_token(name: str) -> str:
    token = name.strip().split("::")[-1].split(".")[-1]
    token = token[:-2] if token.endswith("()") else token
    return token.strip()


def _source_files_for(nodes: list[dict[str, Any]], project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for node in nodes:
        src = _node_source(node)
        if not src or src.startswith(("http://", "https://")):
            continue
        path = Path(src)
        if not path.is_absolute():
            path = project_root / path
        if path.is_file() and path not in paths:
            paths.append(path)
    return paths


def _has_code_evidence(path: Path, subject: str, relation: str, obj: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    sub_token = _code_token(subject)
    obj_token = _code_token(obj)
    rel = relation.strip().casefold()
    if not obj_token:
        return False

    if rel in {"method", "has_method", "defines", "contains"}:
        class_match = re.search(rf"\bclass\s+{re.escape(sub_token)}\b", text) if sub_token else None
        method_match = re.search(rf"\b(def|async\s+def)\s+{re.escape(obj_token)}\b", text)
        return bool(class_match and method_match)

    if rel in {"calls", "call", "uses", "instantiates"}:
        sub_defined = bool(
            sub_token
            and re.search(rf"\b(class|def|async\s+def)\s+{re.escape(sub_token)}\b", text)
        )
        obj_called = bool(re.search(rf"\b{re.escape(obj_token)}\s*\(", text))
        return sub_defined and obj_called

    if rel in {"imports", "import", "from_imports"}:
        return bool(re.search(rf"\b(import|from)\b[^\n]*\b{re.escape(obj_token)}\b", text))

    return False


def _format_node(node: dict[str, Any]) -> str:
    src = _node_source(node)
    label = _label(node)
    return f"{src}::{label}" if src and "::" not in label else label


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _action_with_args(fn: str, args: list[str]) -> str:
    quoted = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
    return f"{fn}({quoted})"


def _suggest_disambiguation(
    raw: dict[str, Any], fn: str, args: list[str], ambiguous_arg_indexes: list[int]
) -> str | None:
    nodes = list(raw.get("nodes") or [])
    new_args = list(args)
    changed = False
    for idx in ambiguous_arg_indexes:
        candidates = _matching_nodes(nodes, args[idx]) or _candidate_qualified_nodes(nodes, args[idx])
        if candidates:
            ranked = sorted(candidates, key=lambda n: (_node_source(n) or "", _label(n)))
            new_args[idx] = _format_node(ranked[0])
            changed = True
    return _action_with_args(fn, new_args) if changed else None


def review_action(raw: dict[str, Any], action: str, *, project_root: Path | None = None) -> ActionReview:
    nodes = list(raw.get("nodes") or [])
    try:
        fn, args = _parse_action_string(action)
    except ValueError as exc:
        return ActionReview(
            action=action,
            confidence="LOW",
            warnings=[str(exc)],
        )

    evidence: list[str] = []
    warnings: list[str] = []
    ambiguous_arg_indexes: list[int] = []

    entity_indexes = [0, 2] if fn in {"insert_edge", "delete_edge"} else [0, 1]
    for idx in entity_indexes:
        if idx >= len(args):
            continue
        name = args[idx]
        query_src, query_label = _split_qualified_label(name.strip())
        is_generic_bare_name = query_src is None and query_label.casefold() in AMBIGUOUS_LABELS
        matches = _matching_nodes(nodes, name)
        qualified_candidates = _candidate_qualified_nodes(nodes, name)
        if matches:
            sources = sorted({s for n in matches if (s := _node_source(n))})
            evidence.append(f"Node exists: {name}" + (f" ({', '.join(sources[:3])})" if sources else ""))
        if is_generic_bare_name:
            warnings.append(f"Ambiguous bare node name: {name!r}; include file or module path.")
            ambiguous_arg_indexes.append(idx)
        if len(matches) > 1:
            warnings.append(f"Ambiguous node name: {name!r} matches {len(matches)} graph nodes.")
            warnings.append("Candidate qualified names: " + "; ".join(_candidate_labels(matches)))
            if idx not in ambiguous_arg_indexes:
                ambiguous_arg_indexes.append(idx)
        elif not matches and len(qualified_candidates) > 1:
            warnings.append(
                f"Ambiguous function name: {name!r} has {len(qualified_candidates)} qualified candidates."
            )
            warnings.append(
                "Candidate qualified names: " + "; ".join(_candidate_labels(qualified_candidates))
            )
            if idx not in ambiguous_arg_indexes:
                ambiguous_arg_indexes.append(idx)

    if fn in {"insert_edge", "delete_edge"} and len(args) >= 3:
        sub_matches = _matching_nodes(nodes, args[0])
        obj_matches = _matching_nodes(nodes, args[2])
        if _edge_exists(raw, sub_matches, args[1], obj_matches):
            evidence.append("Exact edge already exists in graph.json.")
        elif sub_matches and obj_matches:
            evidence.append("Both endpoint nodes exist in graph.json; relation is inferred by refinement loop.")
        if project_root and sub_matches:
            for path in _source_files_for(sub_matches, project_root):
                if _has_code_evidence(path, args[0], args[1], args[2]):
                    evidence.append(f"Direct code evidence in {_display_path(path, project_root)}.")
                    break

    if fn == "replace_node" and len(args) >= 2:
        old_matches = _matching_nodes(nodes, args[0])
        if old_matches:
            evidence.append("Replacement source node exists in graph.json.")
        if _matching_nodes(nodes, args[1]):
            evidence.append("Replacement target node already exists in graph.json.")

    suggested = _suggest_disambiguation(raw, fn, args, ambiguous_arg_indexes)

    if warnings:
        confidence = "LOW"
    elif any(
        "Exact edge already exists" in e
        or "Replacement source node" in e
        or "Direct code evidence" in e
        for e in evidence
    ):
        confidence = "HIGH"
    elif evidence:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
        warnings.append("No direct node or edge evidence found in graph.json.")

    return ActionReview(
        action=action,
        confidence=confidence,
        evidence=evidence,
        warnings=warnings,
        suggested_replacement=suggested,
    )


def review_refinement_text(
    raw: dict[str, Any], refinement_text: str, *, project_root: Path | None = None
) -> list[ActionReview]:
    return [
        review_action(raw, action, project_root=project_root)
        for action in parse_refinement_block(refinement_text)
    ]


def render_review_markdown(reviews: list[ActionReview]) -> str:
    lines = [f"DeepRefine proposed {len(reviews)} refinement action(s).", ""]
    for review in reviews:
        lines.append(f"[{review.confidence}] {review.action}")
        if review.evidence:
            lines.append("Evidence:")
            lines.extend(f"- {item}" for item in review.evidence)
        if review.warnings:
            lines.append("Warning:")
            lines.extend(f"- {item}" for item in review.warnings)
        if review.suggested_replacement:
            lines.append("Suggested replacement:")
            lines.append(f"- {review.suggested_replacement}")
        lines.append("")
    lines.append("Apply only after review: deeprefine apply --refresh-wiki --trace-file <trace> --refinement-file <actions>")
    return "\n".join(lines).rstrip() + "\n"


def write_review_files(
    *,
    graph_path: Path,
    refinement_text: str,
    report_path: Path,
    json_path: Path | None = None,
) -> tuple[list[ActionReview], str]:
    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    project_root = graph_path.parent.parent if graph_path.parent.name == "graphify-out" else None
    reviews = review_refinement_text(raw, refinement_text, project_root=project_root)
    markdown = render_review_markdown(reviews)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps([r.to_dict() for r in reviews], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return reviews, markdown
