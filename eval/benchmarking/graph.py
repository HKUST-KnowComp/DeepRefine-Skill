"""Graphify node-link JSON loading, normalization, and graph traversal."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: object) -> str:
    """Return a stable, case-insensitive representation of a label."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def normalize_relation(value: object) -> str:
    """Normalize a relation while retaining its word-level meaning."""

    text = normalize_text(value).replace("_", " ").replace("-", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_source(value: object) -> str:
    """Normalize a source path without requiring it to exist."""

    text = normalize_text(value).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.removeprefix("./")


def source_matches(left: str, right: str) -> bool:
    """Return whether two normalized source paths identify the same file."""

    if not left or not right:
        return False
    left_norm = normalize_source(left)
    right_norm = normalize_source(right)
    if left_norm == right_norm:
        return True
    return (
        left_norm.endswith("/" + right_norm)
        or right_norm.endswith("/" + left_norm)
        or left_norm.rsplit("/", 1)[-1] == right_norm.rsplit("/", 1)[-1]
    )


@dataclass(frozen=True)
class GraphNode:
    """A normalized view of one Graphify node."""

    id: str
    label: str
    aliases: tuple[str, ...] = ()
    source_file: str = ""
    data: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def normalized_aliases(self) -> frozenset[str]:
        values = {normalize_text(self.label), *(normalize_text(v) for v in self.aliases)}
        values.discard("")
        return frozenset(values)


@dataclass(frozen=True)
class GraphEdge:
    """A normalized view of one Graphify edge."""

    source: str
    target: str
    relation: str
    data: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass
class GraphData:
    """A dependency-free representation of Graphify's node-link graph."""

    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    directed: bool = True
    multigraph: bool = True
    diagnostics: dict[str, int] = field(default_factory=dict)

    def adjacency(self) -> dict[str, list[str]]:
        """Build a deterministic adjacency list, respecting graph direction."""

        result: dict[str, set[str]] = {node_id: set() for node_id in self.nodes}
        for edge in self.edges:
            if edge.source not in result or edge.target not in result:
                continue
            result[edge.source].add(edge.target)
            if not self.directed:
                result[edge.target].add(edge.source)
        return {key: sorted(value) for key, value in result.items()}

    def node_ids_for_aliases(self, aliases: Iterable[object]) -> list[str]:
        """Return node IDs matching any normalized alias."""

        wanted = {normalize_text(alias) for alias in aliases}
        wanted.discard("")
        return sorted(
            node.id
            for node in self.nodes.values()
            if node.normalized_aliases.intersection(wanted)
        )


def _coerce_aliases(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def load_graphify_graph(
    source: str | Path | Mapping[str, Any],
    *,
    strict: bool = False,
) -> GraphData:
    """Load Graphify/NetworkX node-link JSON.

    In non-strict mode malformed edges are skipped and exposed through
    diagnostics.  Structural errors in the top-level document always raise
    ``ValueError``.
    """

    if isinstance(source, Mapping):
        raw = dict(source)
    else:
        path = Path(source)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load graph JSON {path}: {exc}") from exc

    raw_nodes = raw.get("nodes")
    raw_edges = raw.get("links", raw.get("edges"))
    if not isinstance(raw_nodes, list):
        raise ValueError("Graph JSON must contain a 'nodes' array")
    if not isinstance(raw_edges, list):
        raise ValueError("Graph JSON must contain a 'links' or 'edges' array")

    nodes: dict[str, GraphNode] = {}
    duplicate_node_ids = 0
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, Mapping):
            if strict:
                raise ValueError(f"nodes[{index}] must be an object")
            continue
        node_id = str(item.get("id", "")).strip()
        if not node_id:
            if strict:
                raise ValueError(f"nodes[{index}] is missing id")
            continue
        if node_id in nodes:
            duplicate_node_ids += 1
            if strict:
                raise ValueError(f"Duplicate node id: {node_id}")
            continue
        label = str(item.get("label", node_id))
        source_file = str(
            item.get("source_file")
            or item.get("file_id")
            or item.get("source_url")
            or ""
        )
        nodes[node_id] = GraphNode(
            id=node_id,
            label=label,
            aliases=_coerce_aliases(item.get("aliases")),
            source_file=source_file,
            data=dict(item),
        )

    edges: list[GraphEdge] = []
    dangling_edges = 0
    malformed_edges = 0
    edge_counter: Counter[tuple[str, str, str]] = Counter()
    self_loops = 0
    directed = bool(raw.get("directed", True))

    for index, item in enumerate(raw_edges):
        if not isinstance(item, Mapping):
            malformed_edges += 1
            if strict:
                raise ValueError(f"edges[{index}] must be an object")
            continue
        edge_source = str(item.get("source", "")).strip()
        edge_target = str(item.get("target", "")).strip()
        relation = str(item.get("relation", item.get("label", ""))).strip()
        if not edge_source or not edge_target:
            malformed_edges += 1
            if strict:
                raise ValueError(f"edges[{index}] is missing source or target")
            continue
        if edge_source not in nodes or edge_target not in nodes:
            dangling_edges += 1
            if strict:
                raise ValueError(
                    f"Dangling edge {edge_source!r} -> {edge_target!r}"
                )
            continue
        if edge_source == edge_target:
            self_loops += 1

        key_source, key_target = edge_source, edge_target
        if not directed and key_target < key_source:
            key_source, key_target = key_target, key_source
        edge_counter[(key_source, normalize_relation(relation), key_target)] += 1
        edges.append(
            GraphEdge(
                source=edge_source,
                target=edge_target,
                relation=relation,
                data=dict(item),
            )
        )

    duplicate_edges = sum(max(0, count - 1) for count in edge_counter.values())
    return GraphData(
        nodes=nodes,
        edges=edges,
        directed=directed,
        multigraph=bool(raw.get("multigraph", True)),
        diagnostics={
            "duplicate_node_ids": duplicate_node_ids,
            "duplicate_edges": duplicate_edges,
            "dangling_edges": dangling_edges,
            "malformed_edges": malformed_edges,
            "self_loops": self_loops,
        },
    )


def _node_match_score(gold: GraphNode, predicted: GraphNode) -> int:
    if not gold.normalized_aliases.intersection(predicted.normalized_aliases):
        return 0
    if gold.source_file and predicted.source_file:
        return 3 if source_matches(gold.source_file, predicted.source_file) else 1
    return 2


def align_entities(
    gold_nodes: Iterable[GraphNode],
    predicted: GraphData,
) -> dict[str, str]:
    """Greedily align gold nodes to predicted nodes with deterministic ties.

    Exact normalized aliases are required.  Matching source paths receive the
    highest score, and each predicted node can be used at most once.
    """

    candidates: list[tuple[int, str, str]] = []
    for gold in gold_nodes:
        for node in predicted.nodes.values():
            score = _node_match_score(gold, node)
            if score:
                candidates.append((-score, gold.id, node.id))

    result: dict[str, str] = {}
    used_predicted: set[str] = set()
    for _negative_score, gold_id, predicted_id in sorted(candidates):
        if gold_id in result or predicted_id in used_predicted:
            continue
        result[gold_id] = predicted_id
        used_predicted.add(predicted_id)
    return result


def canonical_edge(
    source: str,
    relation: object,
    target: str,
    *,
    directed: bool,
) -> tuple[str, str, str]:
    """Return a comparable edge key."""

    edge_source, edge_target = source, target
    if not directed and edge_target < edge_source:
        edge_source, edge_target = edge_target, edge_source
    return edge_source, normalize_relation(relation), edge_target


def unique_edge_keys(graph: GraphData) -> set[tuple[str, str, str]]:
    """Return unique normalized graph triples while preserving parallel relations."""

    return {
        canonical_edge(
            edge.source,
            edge.relation,
            edge.target,
            directed=graph.directed,
        )
        for edge in graph.edges
    }


def bounded_bfs(
    graph: GraphData,
    start_ids: Iterable[str],
    max_hops: int,
) -> dict[str, int]:
    """Return the shortest hop distance to nodes reachable within ``max_hops``."""

    if max_hops < 0:
        raise ValueError("max_hops must be non-negative")
    starts = sorted({node_id for node_id in start_ids if node_id in graph.nodes})
    distances = {node_id: 0 for node_id in starts}
    queue: deque[str] = deque(starts)
    adjacency = graph.adjacency()
    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= max_hops:
            continue
        for neighbor in adjacency.get(current, ()):
            if neighbor in distances:
                continue
            distances[neighbor] = distance + 1
            queue.append(neighbor)
    return distances
