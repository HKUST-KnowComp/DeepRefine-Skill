"""Import Obsidian-style [[wikilink]] markdown directories into graph.json.

POC module for the LLM-Wiki extension of DeepRefine-Skill.
Parses .md files, extracts [[wikilinks]] via regex, and outputs:
  - graph.json: node-link graph compatible with existing refine pipeline
  - page_contents.json: full page text for retrieval

Only stdlib dependencies (json, re, pathlib).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Matches [[Page]], [[Page|alias]], [[Page#heading]], [[Page#heading|alias]]
# Group 1 captures only the page name (before | or #)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def _slug(text: str) -> str:
    """Convert arbitrary text to a kebab-case identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "page"


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (between --- fences) if present."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _extract_title(text: str) -> str | None:
    """Extract the first # heading from markdown text (after frontmatter)."""
    body = _strip_frontmatter(text)
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def _extract_snippet(text: str, max_chars: int = 200) -> str:
    """Extract a clean content snippet: first N chars, wikilinks resolved."""
    body = _strip_frontmatter(text)
    # Remove heading lines
    body = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)
    # Resolve [[Link|alias]] → Link
    body = re.sub(r"\[\[([^\]|#]+)(?:\|[^\]]+)?(?:\#[^\]]+)?\]\]", r"\1", body)
    # Collapse whitespace
    body = re.sub(r"\s+", " ", body).strip()
    return body[:max_chars]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_links(md_text: str) -> list[str]:
    """Extract all [[link]] target page names from markdown text.

    Returns page names in order of first occurrence (deduplicated).
    Handles: [[Page]], [[Page|alias]], [[Page#heading]], [[Page#heading|alias]].
    """
    seen: set[str] = set()
    result: list[str] = []
    for m in WIKILINK_RE.finditer(md_text):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def parse_md_file(filepath: Path) -> dict:
    """Parse a single .md file.

    Returns:
        {"id": page_id, "label": title, "links": [link_names...], "content": raw_text}
    """
    text = filepath.read_text(encoding="utf-8", errors="ignore")
    page_id = filepath.stem
    label = _extract_title(text) or page_id
    links = extract_links(text)
    return {"id": page_id, "label": label, "links": links, "content": text}


def build_graph(wiki_dir: Path) -> dict:
    """Scan wiki_dir for .md files and build a graph.json-compatible dict.

    Two-pass algorithm:
      1. Parse all files → build nodes + label→id lookup
      2. Resolve [[links]] → build edges (deduplicated)

    Nodes use ``page_path`` (absolute path) — NOT ``source_file`` —
    so that action_review.py can distinguish wiki from code nodes.

    Returns:
        {"nodes": [...], "links": [...]}
    """
    wiki_dir = wiki_dir.resolve()
    md_files = sorted(wiki_dir.glob("*.md"))

    # --- Pass 1: nodes + label→id lookup ---
    nodes: list[dict] = []
    label_to_id: dict[str, str] = {}  # casefold(label|id) → node id

    for md_file in md_files:
        parsed = parse_md_file(md_file)
        nid = parsed["id"]
        nodes.append(
            {
                "id": nid,
                "label": parsed["label"],
                "page_path": str(md_file.resolve()),
                "content_snippet": _extract_snippet(parsed["content"]),
            }
        )
        # Register both id and label → id (case-insensitive)
        label_to_id[nid.casefold()] = nid
        label_to_id[parsed["label"].casefold()] = nid

    # --- Pass 2: links ---
    links: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    for md_file in md_files:
        parsed = parse_md_file(md_file)
        source_id = parsed["id"]

        for link_text in parsed["links"]:
            # Resolve link text to an existing node ID
            target_id = label_to_id.get(link_text.strip().casefold())
            if target_id is None:
                # Dangling link — use slug-ified text; deeprefine may
                # later suggest creating a node for this target.
                target_id = _slug(link_text.strip())

            edge_key = (source_id, target_id)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                links.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "relation": "links_to",
                    }
                )

    return {"nodes": nodes, "links": links}


def build_page_contents(wiki_dir: Path) -> dict:
    """Build a page_contents.json mapping for retrieval.

    Returns:
        {page_id: {"path": str, "title": str, "content": str}, ...}
    """
    wiki_dir = wiki_dir.resolve()
    contents: dict[str, dict] = {}
    for md_file in sorted(wiki_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        page_id = md_file.stem
        contents[page_id] = {
            "path": str(md_file),
            "title": _extract_title(text) or page_id,
            "content": text,
        }
    return contents


def import_wiki(wiki_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    """Main entry point: import a wiki directory into graph.json + page_contents.json.

    Args:
        wiki_dir: Directory containing .md files with [[wikilinks]].
        output_dir: Where to write graph.json and page_contents.json.

    Returns:
        (graph_json_path, page_contents_json_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = build_graph(wiki_dir)
    graph_path = output_dir / "graph.json"
    graph_path.write_text(
        json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    pages = build_page_contents(wiki_dir)
    pages_path = output_dir / "page_contents.json"
    pages_path.write_text(
        json.dumps(pages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return graph_path, pages_path
