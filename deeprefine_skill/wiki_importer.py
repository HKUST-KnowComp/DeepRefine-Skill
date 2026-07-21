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

# Matches [text](url) markdown links — GitHub Wiki, Gitit, etc.
# Group 1: display text, Group 2: URL
MDLINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")

# Common text file extensions used by LLM-wiki systems.
# Obsidian/Logseq/Roam: .md; GitHub Wiki: .md; Gitit: .txt, .markdown, etc.
_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".mdown", ".mdwn", ".mkd", ".mkdn",
    ".txt", ".text", ".rst",
}

# URL prefixes / schemes that disqualify a markdown link as an internal
# wiki page reference.
_INTERNAL_LINK_SKIP_PREFIXES = ("http://", "https://", "ftp://", "mailto:", "#")

# File extensions that are clearly NOT wiki pages.  Links pointing to
# images, PDFs, archives, or media files are excluded from link counting
# so that inline assets are not mistaken for page references.
_NON_PAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
}


def _is_internal_wiki_link(url: str) -> bool:
    """Return True if *url* points to another wiki page (not an anchor,
    external URL, or non-page asset)."""
    stripped = url.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if lower.startswith(_INTERNAL_LINK_SKIP_PREFIXES):
        return False
    suffix = Path(stripped).suffix.lower()
    if suffix in _NON_PAGE_EXTENSIONS:
        return False
    return True


def _slug(text: str) -> str:
    """Convert arbitrary text to a kebab-case identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "page"


def detect_link_format(text: str) -> str:
    """Detect the primary link convention used in *text*.

    Returns one of:
      ``"wikilink"`` — ``[[Page]]`` links are the majority (or tie)
      ``"mdlink"``  — ``[text](url)`` links outnumber wikilinks
      ``"none"``    — no recognised links found

    Anchors (``#section``), external URLs, and non-page assets (images,
    PDFs, archives, media) are excluded from counting so they are not
    mistaken for wiki page references.
    """
    wiki_count = len(WIKILINK_RE.findall(text))

    mdlink_count = 0
    for m in MDLINK_RE.finditer(text):
        if _is_internal_wiki_link(m.group(2)):
            mdlink_count += 1

    if wiki_count == 0 and mdlink_count == 0:
        return "none"
    if wiki_count >= mdlink_count:
        return "wikilink"
    return "mdlink"


def _find_wiki_files(wiki_dir: Path) -> list[Path]:
    """Find text files that could be wiki pages in *wiki_dir*.

    Uses a whitelist of common text extensions.  For files without a
    recognised extension the first 4 KiB are scanned for link patterns
    (wikilink or internal markdown link).

    Only the top-level directory is scanned (non-recursive).
    Binary / unreadable files are silently skipped.
    """
    found: list[Path] = []

    for child in sorted(wiki_dir.iterdir()):
        if not child.is_file():
            continue

        suffix = child.suffix.lower()
        if suffix in _TEXT_EXTENSIONS:
            found.append(child)
            continue

        # No recognised extension — content-based detection
        try:
            head = child.read_text(encoding="utf-8", errors="ignore")[:4096]
        except Exception:
            continue  # binary or unreadable

        if WIKILINK_RE.search(head):
            found.append(child)
            continue
        # Check for internal markdown links
        for m in MDLINK_RE.finditer(head):
            if _is_internal_wiki_link(m.group(2)):
                found.append(child)
                break

    return found


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (between --- fences) if present."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _extract_title(text: str) -> str | None:
    """Extract the first # heading from markdown text (after frontmatter).

    Falls back to the ``title:`` field in YAML frontmatter if no heading
    is found (common in GitHub Wiki and some Obsidian vaults).
    """
    body = _strip_frontmatter(text)
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()

    # Fallback: frontmatter title: field
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_match = re.search(r"^title:\s*(.+)$", parts[1], re.MULTILINE)
            if fm_match:
                title = fm_match.group(1).strip()
                # Strip optional surrounding quotes
                if len(title) >= 2 and title[0] in ('"', "'") and title[0] == title[-1]:
                    title = title[1:-1]
                return title

    return None


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
    """Extract all link target page names from markdown text.

    Handles both ``[[wikilinks]]`` and ``[text](url)`` markdown links.
    External URLs (http, https, ftp, mailto) are excluded.

    Returns page names in order of first occurrence (deduplicated).
    """
    seen: set[str] = set()
    result: list[str] = []

    # Wikilinks
    for m in WIKILINK_RE.finditer(md_text):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)

    # Markdown links — use display text as the page name, deduped
    for m in MDLINK_RE.finditer(md_text):
        url = m.group(2)
        if not _is_internal_wiki_link(url):
            continue
        # Page name from display text, falling back to URL stem
        display = m.group(1).strip()
        if display:
            name = display
        else:
            name = Path(url).stem
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
    link_format = detect_link_format(text)
    links = extract_links(text)
    return {
        "id": page_id,
        "label": label,
        "links": links,
        "content": text,
        "link_format": link_format,
    }


def build_graph(wiki_dir: Path) -> dict:
    """Scan wiki_dir for wiki files and build a graph.json-compatible dict.

    Two-pass algorithm:
      1. Parse all files → build nodes + label→id lookup
      2. Resolve links → build edges (deduplicated)

    Nodes use ``page_path`` (absolute path) — NOT ``source_file`` —
    so that action_review.py can distinguish wiki from code nodes.

    Each node carries a ``link_format`` field (``"wikilink"`` or
    ``"mdlink"``) so that the write-back layer can use the same
    convention as the original file.

    Returns:
        {"nodes": [...], "links": [...], "link_format": "wikilink"}
    """
    wiki_dir = wiki_dir.resolve()
    wiki_files = _find_wiki_files(wiki_dir)

    # --- Pass 1: nodes + label→id lookup ---
    nodes: list[dict] = []
    label_to_id: dict[str, str] = {}  # casefold(label|id) → node id

    for wf in wiki_files:
        parsed = parse_md_file(wf)
        nid = parsed["id"]
        nodes.append(
            {
                "id": nid,
                "label": parsed["label"],
                "page_path": str(wf.resolve()),
                "content_snippet": _extract_snippet(parsed["content"]),
                "link_format": parsed["link_format"],
            }
        )
        # Register both id and label → id (case-insensitive)
        label_to_id[nid.casefold()] = nid
        label_to_id[parsed["label"].casefold()] = nid

    # --- Pass 2: links ---
    links: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    for wf in wiki_files:
        parsed = parse_md_file(wf)
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

    # Determine wiki-wide dominant format (majority vote across nodes)
    all_formats = [n.get("link_format", "none") for n in nodes]
    dominant = max(set(all_formats), key=all_formats.count) if all_formats else "none"

    return {"nodes": nodes, "links": links, "link_format": dominant}


def build_page_contents(wiki_dir: Path) -> dict:
    """Build a page_contents.json mapping for retrieval.

    Returns:
        {page_id: {"path": str, "title": str, "content": str}, ...}
    """
    wiki_dir = wiki_dir.resolve()
    contents: dict[str, dict] = {}
    for wf in _find_wiki_files(wiki_dir):
        text = wf.read_text(encoding="utf-8", errors="ignore")
        page_id = wf.stem
        contents[page_id] = {
            "path": str(wf),
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
