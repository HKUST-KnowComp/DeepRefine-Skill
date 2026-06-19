#!/usr/bin/env python3
"""Validate a graph.json file against the graphify schema.

Usage:
    python scripts/validate_graph_schema.py path/to/graph.json
    python scripts/validate_graph_schema.py fixtures/synth-minimal.json

Exit code 0 = valid, 1 = errors found.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# nodes, hyperedges are required.
# 'edges' or 'links' — at least one must be present.
# input_tokens/output_tokens are only present when graphify does LLM extraction;
# they are optional.
TOP_LEVEL_REQUIRED = {"nodes", "hyperedges"}
TOP_LEVEL_EDGE_KEYS = {"edges", "links"}
TOP_LEVEL_OPTIONAL = {"input_tokens", "output_tokens", "directed", "multigraph", "graph", "built_at_commit"}
NODE_REQUIRED_KEYS = {"id", "label", "source_file"}
EDGE_REQUIRED_KEYS = {"source", "target", "relation", "confidence", "confidence_score", "source_file"}
VALID_CONFIDENCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def validate_graph(data: dict) -> list[str]:
    errors: list[str] = []

    # --- top-level keys ---
    for key in TOP_LEVEL_REQUIRED:
        if key not in data:
            errors.append(f"missing required top-level key: {key!r}")

    has_edge_key = any(k in data for k in TOP_LEVEL_EDGE_KEYS)
    if not has_edge_key:
        errors.append(f"missing edge key — need one of: {TOP_LEVEL_EDGE_KEYS}")

    for key in TOP_LEVEL_OPTIONAL:
        if key not in data:
            pass  # optional — no error

    nodes: list[dict] = data.get("nodes", [])
    edges: list[dict] = data.get("edges", data.get("links", []))
    # hyperedges, input_tokens, output_tokens are optional in practice
    # but graphify always includes them

    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list")
        return errors
    if not isinstance(edges, list):
        errors.append("'edges' (or 'links') must be a list")
        return errors

    # --- nodes ---
    node_ids: set[str] = set()
    for i, n in enumerate(nodes):
        for key in NODE_REQUIRED_KEYS:
            if key not in n:
                errors.append(f"node[{i}]: missing field {key!r}")
        nid = n.get("id")
        if nid is not None:
            if nid in node_ids:
                errors.append(f"node[{i}]: duplicate id {nid!r}")
            node_ids.add(str(nid))

    if not node_ids:
        errors.append("at least one node required")

    # --- edges ---
    for i, e in enumerate(edges):
        for key in EDGE_REQUIRED_KEYS:
            if key not in e:
                errors.append(f"edge[{i}]: missing field {key!r}")

        conf = e.get("confidence", "")
        if conf and conf not in VALID_CONFIDENCE:
            errors.append(
                f"edge[{i}]: confidence={conf!r} must be EXTRACTED, INFERRED, or AMBIGUOUS"
            )

        score = e.get("confidence_score")
        if score is not None:
            if not isinstance(score, (int, float)) or not (0.0 <= float(score) <= 1.0):
                errors.append(
                    f"edge[{i}]: confidence_score={score!r} must be float in [0.0, 1.0]"
                )

        src = e.get("source", "")
        tgt = e.get("target", "")
        if src and src not in node_ids:
            errors.append(f"edge[{i}]: source {src!r} not in nodes")
        if tgt and tgt not in node_ids:
            errors.append(f"edge[{i}]: target {tgt!r} not in nodes")

    # --- hyperedges ---
    hyperedges = data.get("hyperedges", [])
    if isinstance(hyperedges, list):
        for i, h in enumerate(hyperedges):
            if "id" not in h:
                errors.append(f"hyperedge[{i}]: missing 'id'")
            if "nodes" not in h:
                errors.append(f"hyperedge[{i}]: missing 'nodes'")
    elif hyperedges is not None:
        errors.append("'hyperedges' must be a list or null")

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} path/to/graph.json", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        return 1

    errors = validate_graph(data)

    if errors:
        print(f"FAIL: {path} has {len(errors)} schema violation(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"OK: {path} — {len(data.get('nodes',[]))} nodes, {len(data.get('edges', data.get('links',[])))} edges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
