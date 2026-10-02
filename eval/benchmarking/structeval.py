"""Scoped structural evaluation of a Graphify graph against mechanical AST gold.

The import subgraph is the one slice of a code knowledge graph whose gold
is mechanically decidable (see ``ast_gold``), so precision and recall here
are exact numbers, not estimates.  This evaluator deliberately does NOT
ride the generic suite evaluator: with partial gold (import edges only)
the generic triple-F1 semantics would be wrong — every non-import edge
would count as a false positive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .ast_gold import GoldAST, gold_to_jsonable
from .graph import (
    GraphData,
    load_graphify_graph,
    normalize_relation,
    normalize_source,
    normalize_text,
    source_matches,
)
from .metrics import precision_recall_f1


SCHEMA_VERSION = 1

# Relations under which Graphify claims an import.  ``imports_from``
# normalizes to ``imports from``; anything else is a semantic claim
# (calls/references/...) and out of scope here.
IMPORT_RELATIONS = {"imports", "imports from"}

_MAX_DETAIL_LINES = 25


def _node_path(node) -> str:
    """Best available path identity for a graph node, normalized."""

    if node.source_file:
        return normalize_source(node.source_file)
    return normalize_source(node.label)


def _is_module_node(node) -> bool:
    return normalize_text(node.label).endswith(".py")


def _symbol_name(label: str) -> str:
    text = normalize_text(label)
    if text.endswith("()"):
        text = text[:-2].strip()
    return text


def _format_dependency(source: str, target: str) -> str:
    return f"{source} -> {target}"


def _format_symbol(source: str, target: str, symbol: str) -> str:
    return f"{source} -> {target}::{symbol}"


def _key_matches(predicted: tuple, gold: tuple) -> bool:
    """Match one predicted key component-wise against a gold key.

    Component order is ``(source, target[, symbol])``.  Path components
    match exactly or by suffix (``source_matches``). Every predicted
    component is required: in particular, a symbol node without a defining
    module must not receive credit for a full ``(source, target, symbol)``
    import edge.
    """

    for got, want in zip(predicted, gold):
        if got == want:
            continue
        if not got:
            return False
        if not want:
            return False
        if not source_matches(got, want):
            return False
    return True


def _match_keys(
    predicted: list[tuple],
    gold: set[tuple],
) -> tuple[set[tuple], set[tuple], list[tuple]]:
    """Match predicted keys against gold keys with exact-then-suffix fallback.

    Returns ``(matched_predicted, matched_gold, unverified_predicted)``.
    Exact normalized equality is tried first; the fallback allows a
    suffix path match (``source_matches``) on every component so leading
    ``./``-style drift does not create false failures.
    """

    matched_pred: set[tuple] = set()
    matched_gold: set[tuple] = set()
    unverified: list[tuple] = []
    ordered_gold = sorted(gold)
    for key in sorted(predicted):
        hit = None
        if key in gold:
            hit = key
        else:
            for candidate in ordered_gold:
                if len(candidate) != len(key):
                    continue
                if _key_matches(key, candidate):
                    hit = candidate
                    break
        if hit is not None:
            matched_pred.add(key)
            matched_gold.add(hit)
        else:
            unverified.append(key)
    return matched_pred, matched_gold, unverified


def evaluate_structure(
    gold: GoldAST,
    graph_source: str | Path | Mapping[str, Any],
) -> dict[str, Any]:
    """Score a Graphify graph's module entities and import subgraph.

    Returns a JSON-able result dict.  Deterministic for identical inputs.
    """

    graph: GraphData = load_graphify_graph(graph_source)
    gold_modules = set(gold.modules)
    gold_deps = {
        (normalize_source(src), normalize_source(tgt))
        for src, tgt in gold.module_dependencies()
    }
    gold_syms = {
        (normalize_source(src), normalize_source(tgt), normalize_text(sym))
        for src, tgt, sym in gold.symbol_imports()
    }

    module_nodes = [node for node in graph.nodes.values() if _is_module_node(node)]

    # --- Module entities: one-to-one greedy alignment, deterministic by id.
    matched_nodes: dict[str, str] = {}
    used_gold: set[str] = set()
    for node in sorted(module_nodes, key=lambda item: item.id):
        path = _node_path(node)
        hit = ""
        if path in gold_modules and path not in used_gold:
            hit = path
        else:
            for candidate in sorted(gold_modules - used_gold):
                if source_matches(path, candidate):
                    hit = candidate
                    break
        if hit:
            matched_nodes[node.id] = hit
            used_gold.add(hit)

    module_tp = len(matched_nodes)
    module_prf = precision_recall_f1(
        module_tp,
        len(module_nodes) - module_tp,
        len(gold_modules) - module_tp,
    )
    phantom_modules = sorted(
        _node_path(node) for node in module_nodes if node.id not in matched_nodes
    )
    missing_modules = sorted(gold_modules - used_gold)

    # --- Import claims, split by claimed granularity.
    dep_pred: set[tuple[str, str]] = set()
    sym_pred: set[tuple[str, str, str]] = set()
    malformed_claims: list[str] = []
    for edge in graph.edges:
        if normalize_relation(edge.relation) not in IMPORT_RELATIONS:
            continue
        source_node = graph.nodes[edge.source]
        target_node = graph.nodes[edge.target]
        if not _is_module_node(source_node):
            malformed_claims.append(
                f"{source_node.label!r} -{edge.relation}-> {target_node.label!r}"
            )
            continue
        source_path = _node_path(source_node)
        if _is_module_node(target_node):
            dep_pred.add((source_path, _node_path(target_node)))
        else:
            # Symbol claims key as (source, target, symbol); an empty
            # target path (symbol node without source_file) acts as a
            # wildcard for the defining module.
            target_path = (
                normalize_source(target_node.source_file)
                if target_node.source_file
                else ""
            )
            sym_pred.add((source_path, target_path, _symbol_name(target_node.label)))

    dep_matched, dep_gold_matched, dep_unverified = _match_keys(
        sorted(dep_pred), gold_deps
    )
    dep_prf = precision_recall_f1(
        len(dep_matched),
        len(dep_pred) - len(dep_matched),
        len(gold_deps) - len(dep_gold_matched),
    )

    sym_matched, sym_gold_matched, sym_unverified = _match_keys(
        sorted(sym_pred), gold_syms
    )
    sym_prf = precision_recall_f1(
        len(sym_matched),
        len(sym_pred) - len(sym_matched),
        len(gold_syms) - len(sym_gold_matched),
    )

    # Symbol claims whose target node carries a foreign source_file are
    # already rejected by the triple fallback; also surface symbol claims
    # that only match on (source, symbol) but not the defining module.
    unverified_claims = sorted(
        [
            *(_format_dependency(src, tgt) for src, tgt in dep_unverified),
            *(_format_symbol(src, tgt, sym) for src, tgt, sym in sym_unverified),
        ]
    )

    raw_built_at = ""
    if not isinstance(graph_source, Mapping):
        path = Path(graph_source)
        try:
            raw_built_at = str(
                json.loads(path.read_text(encoding="utf-8")).get("built_at_commit", "")
            )
        except (OSError, json.JSONDecodeError):
            raw_built_at = ""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "structural",
        "gold": gold_to_jsonable(gold),
        "graph": {
            "built_at_commit": raw_built_at,
            "commit_matches_gold": bool(
                raw_built_at and gold.commit and raw_built_at == gold.commit
            ),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "claimed_import_edges": len(dep_pred) + len(sym_pred),
            "diagnostics": dict(graph.diagnostics),
        },
        "metrics": {
            "module_nodes": module_prf.as_dict(),
            "module_dependencies": dep_prf.as_dict(),
            "symbol_imports": sym_prf.as_dict(),
        },
        "details": {
            "phantom_module_nodes": phantom_modules,
            "missing_module_nodes": missing_modules,
            "missing_module_dependencies": sorted(
                _format_dependency(src, tgt)
                for src, tgt in (gold_deps - dep_gold_matched)
            ),
            "missing_symbol_imports": sorted(
                _format_symbol(src, tgt, sym)
                for src, tgt, sym in (gold_syms - sym_gold_matched)
            ),
            "unverified_import_edges": unverified_claims,
            "malformed_import_claims": sorted(malformed_claims),
        },
    }


def compare_runs(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Diff a candidate structeval result against its baseline.

    This is the Stage-2 hook: after a real refine run, the same command
    re-evaluated on the refined graph yields the transition view — which
    missing gold edges were recovered, which persist, and which new
    claims the refinement introduced without AST support.
    """

    def detail_keys(result: Mapping[str, Any], field: str) -> set[str]:
        values = result.get("details", {}).get(field, [])
        return {str(value) for value in values}

    baseline_missing_deps = detail_keys(baseline, "missing_module_dependencies")
    candidate_missing_deps = detail_keys(candidate, "missing_module_dependencies")
    baseline_missing_syms = detail_keys(baseline, "missing_symbol_imports")
    candidate_missing_syms = detail_keys(candidate, "missing_symbol_imports")
    baseline_unverified = detail_keys(baseline, "unverified_import_edges")
    candidate_unverified = detail_keys(candidate, "unverified_import_edges")

    return {
        "module_dependencies": {
            "recovered_0_to_1": sorted(baseline_missing_deps - candidate_missing_deps),
            "still_missing": sorted(baseline_missing_deps & candidate_missing_deps),
        },
        "symbol_imports": {
            "recovered_0_to_1": sorted(baseline_missing_syms - candidate_missing_syms),
            "still_missing": sorted(baseline_missing_syms & candidate_missing_syms),
        },
        "unverified_import_edges": {
            "resolved": sorted(baseline_unverified - candidate_unverified),
            "persistent": sorted(baseline_unverified & candidate_unverified),
            "new_unverified": sorted(candidate_unverified - baseline_unverified),
        },
    }


def emit_queries(
    result: Mapping[str, Any],
    destination: str | Path,
) -> int:
    """Write refinement queries targeting the missing gold edges.

    One JSONL line per missing edge — the Stage-2 refine queue.  Queries
    are guided (derived from gold), so the resulting transition metrics
    measure guided recovery and must be reported as such.
    """

    lines: list[dict[str, str]] = []
    index = 0
    for dep in result.get("details", {}).get("missing_module_dependencies", []):
        source, _, target = str(dep).partition(" -> ")
        lines.append(
            {
                "id": f"sq-{index:03d}",
                "kind": "module_dependency",
                "query": f"How does {source} depend on {target}?",
                "gold": str(dep),
            }
        )
        index += 1
    for symbol in result.get("details", {}).get("missing_symbol_imports", []):
        left, _, rest = str(symbol).partition(" -> ")
        target, _, name = rest.partition("::")
        lines.append(
            {
                "id": f"sq-{index:03d}",
                "kind": "symbol_import",
                "query": f"Where does {left} get `{name}` from?",
                "gold": str(symbol),
            }
        )
        index += 1

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines),
        encoding="utf-8",
    )
    return len(lines)


def render_structural_report(result: Mapping[str, Any]) -> str:
    """Render a structeval result dict as a Markdown report."""

    metrics = result.get("metrics", {})
    details = result.get("details", {})
    graph = result.get("graph", {})
    gold = result.get("gold", {})

    rows = []
    for label, key in (
        ("Module nodes", "module_nodes"),
        ("Module dependency edges", "module_dependencies"),
        ("Module->symbol import edges", "symbol_imports"),
    ):
        values = metrics.get(key, {})
        rows.append(
            f"| {label} | {values.get('precision', 0.0) * 100:.2f}% "
            f"| {values.get('recall', 0.0) * 100:.2f}% "
            f"| {values.get('f1', 0.0) * 100:.2f}% "
            f"| {values.get('tp', 0)} | {values.get('fp', 0)} | {values.get('fn', 0)} |"
        )

    commit_match = graph.get("commit_matches_gold")
    if commit_match is True:
        match_line = "yes — graph was built from the same commit as the gold"
    elif commit_match is False:
        match_line = (
            f"**NO** — graph `built_at_commit={graph.get('built_at_commit') or 'unknown'}` "
            f"differs from gold commit `{gold.get('commit') or 'unknown'}`"
        )
    else:
        match_line = "unknown — missing commit provenance on one side"

    def detail_section(title: str, values: list[str] | None) -> list[str]:
        entries = [str(value) for value in (values or [])]
        if not entries:
            return [f"### {title} (0)", "", "None.", ""]
        shown = entries[:_MAX_DETAIL_LINES]
        body = [f"- {entry}" for entry in shown]
        if len(entries) > len(shown):
            body.append(f"- … and {len(entries) - len(shown)} more")
        return [f"### {title} ({len(entries)})", "", *body, ""]

    lines = [
        "# Structural Evaluation",
        "",
        "Scoped structural metrics for a Graphify code graph against "
        "mechanical AST gold (import subgraph + module entities).",
        "",
        "## Provenance",
        "",
        "| | |",
        "|---|---|",
        f"| Gold source tag | `{gold.get('source_tag') or 'n/a'}` "
        f"(commit `{gold.get('commit') or 'unknown'}`) |",
        f"| Graph `built_at_commit` | `{graph.get('built_at_commit') or 'unknown'}` |",
        f"| Commit match | {match_line} |",
        f"| Graph size | {graph.get('node_count', 0)} nodes, "
        f"{graph.get('edge_count', 0)} edges "
        f"({graph.get('claimed_import_edges', 0)} claimed import edges) |",
        f"| Gold size | {gold.get('module_count', 0)} modules, "
        f"{gold.get('module_dependency_count', 0)} module dependencies, "
        f"{gold.get('symbol_import_count', 0)} symbol imports |",
        "",
        "## Metrics",
        "",
        "| Slice | Precision | Recall | F1 | TP | FP | FN |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
        *detail_section(
            "Phantom module nodes (predicted, no gold module)",
            details.get("phantom_module_nodes"),
        ),
        *detail_section(
            "Missing modules (gold, no predicted node)",
            details.get("missing_module_nodes"),
        ),
        *detail_section(
            "Missing module dependencies (gold, not claimed)",
            details.get("missing_module_dependencies"),
        ),
        *detail_section(
            "Missing symbol imports (gold, not claimed)",
            details.get("missing_symbol_imports"),
        ),
        *detail_section(
            "Unverified import claims (claimed, AST cannot prove)",
            details.get("unverified_import_edges"),
        ),
        *detail_section(
            "Malformed import claims (non-module source)",
            details.get("malformed_import_claims"),
        ),
    ]

    transitions = result.get("transitions")
    if isinstance(transitions, Mapping):
        lines.extend(
            [
                "## Transitions vs baseline",
                "",
                "```json",
                json.dumps(transitions, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Scope",
            "",
            "These numbers cover only the mechanically decidable slice: "
            "module entities and import-relation edges.  Semantic edges "
            "(`calls`/`references`/`rationale_for`/...) are NOT scored "
            "here and need sampled human review.  Refinement queries "
            "derived from gold are *guided* recovery — report Stage-2 "
            "transitions as guided results.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "compare_runs",
    "emit_queries",
    "evaluate_structure",
    "render_structural_report",
]
