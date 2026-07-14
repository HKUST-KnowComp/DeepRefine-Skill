"""Wiki retrieval: full-text search + k-hop BFS subgraph expansion.

POC module for the LLM-Wiki extension of DeepRefine-Skill.
Provides retrieval capabilities analogous to ``graphify query`` for code KGs:

  1. Full-text substring search across page contents → entry pages
  2. BFS k-hop expansion along [[links]] → subgraph triples

Output triple format matches the existing graphify query format:
  [{"subject": "A", "relation": "links_to", "object": "B"}, ...]

Only stdlib dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_graph(graph) -> dict:
    """Accept either a Path or an already-loaded dict."""
    if isinstance(graph, (str, Path)):
        return json.loads(Path(graph).read_text(encoding="utf-8"))
    return graph


def _load_pages(pages) -> dict:
    """Accept either a Path or an already-loaded dict."""
    if isinstance(pages, (str, Path)):
        return json.loads(Path(pages).read_text(encoding="utf-8"))
    return pages


def _page_label(page_id: str, page_contents: dict | None) -> str:
    """Return the human-readable title for a page, falling back to the id."""
    if page_contents and page_id in page_contents:
        return page_contents[page_id].get("title", page_id)
    return page_id


def _build_adjacency(graph: dict) -> dict[str, list[str]]:
    """Build adjacency list {source_id: [target_id, ...]} from graph links."""
    adj: dict[str, list[str]] = {}
    links = graph.get("links") or graph.get("edges") or []
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        if src and tgt:
            adj.setdefault(src, []).append(tgt)
    return adj


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_pages(
    query: str, page_contents: dict, top_k: int = 5
) -> list[str]:
    """Full-text substring search across wiki page contents.

    Scores each page by how many query terms appear in its title + content.
    Returns the top-k matching page IDs, ordered by score (descending).

    Args:
        query: Natural-language query string.
        page_contents: ``{page_id: {"title": str, "content": str}}`` dict.
        top_k: Maximum number of results to return.

    Returns:
        List of page IDs, best match first.  Empty list if nothing matches.
    """
    if not query.strip():
        return []

    query_terms = query.lower().split()
    scored: list[tuple[int, str]] = []

    for page_id, info in page_contents.items():
        title = (info.get("title") or "").lower()
        content = (info.get("content") or "").lower()
        combined = f"{title} {content}"

        # Score: count of distinct query terms found in the page
        score = sum(1 for term in query_terms if term in combined)
        if score > 0:
            scored.append((score, page_id))

    # Sort by score descending, then alphabetically by id for stability
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [pid for _, pid in scored[:top_k]]


def k_hop_expand(
    start_pages: list[str],
    graph: dict,
    k: int = 4,
    page_contents: dict | None = None,
) -> list[dict]:
    """BFS from *start_pages* along [[links]], returning subgraph triples.

    Args:
        start_pages: Entry-point page IDs.
        graph: Loaded graph dict with ``"links"`` (or ``"edges"``).
        k: Maximum BFS depth (hops).
        page_contents: Optional ``{page_id: {title, content}}`` for labels.

    Returns:
        List of triples: ``[{"subject": "…", "relation": "links_to", "object": "…"}, …]``.
        Subjects and objects use human-readable labels when *page_contents*
        is provided, falling back to node IDs.
    """
    adj = _build_adjacency(graph)

    visited_nodes: set[str] = set(start_pages)
    visited_edges: set[tuple[str, str]] = set()
    frontier = list(start_pages)

    for _ in range(k):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbor in adj.get(node, []):
                edge_key = (node, neighbor)
                if edge_key not in visited_edges:
                    visited_edges.add(edge_key)
                    if neighbor not in visited_nodes:
                        visited_nodes.add(neighbor)
                        next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    triples: list[dict] = []
    for src, tgt in visited_edges:
        triples.append(
            {
                "subject": _page_label(src, page_contents),
                "relation": "links_to",
                "object": _page_label(tgt, page_contents),
            }
        )

    return triples


def retrieve(
    query: str,
    graph,
    page_contents,
    top_k: int = 5,
    max_hops: int = 4,
) -> dict:
    """Full retrieval pipeline: search → BFS → subgraph triples.

    Args:
        query: Natural-language query.
        graph: Path to graph.json, or an already-loaded dict.
        page_contents: Path to page_contents.json, or an already-loaded dict.
        top_k: Number of entry pages from text search.
        max_hops: Maximum BFS depth.

    Returns:
        {
            "method": "wiki_search+k_hop_expansion",
            "entry_pages": ["page_id", ...],
            "subgraph": [{"subject": …, "relation": …, "object": …}, …],
            "hops": actual_hops_used,
        }
    """
    graph = _load_graph(graph)
    page_contents = _load_pages(page_contents)

    entry_pages = search_pages(query, page_contents, top_k=top_k)

    if not entry_pages:
        return {
            "method": "wiki_search+k_hop_expansion",
            "entry_pages": [],
            "subgraph": [],
            "hops": 0,
        }

    subgraph = k_hop_expand(
        entry_pages, graph, k=max_hops, page_contents=page_contents
    )

    # Estimate actual hops used (depth of BFS that found new edges)
    # Simplified: just report the parameter; a precise count would
    # require tracking the hop at which each edge was discovered.
    hops = max_hops

    return {
        "method": "wiki_search+k_hop_expansion",
        "entry_pages": entry_pages,
        "subgraph": subgraph,
        "hops": hops,
    }
