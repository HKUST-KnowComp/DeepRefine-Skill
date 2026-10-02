"""Non-semantic integrity checks for a generated Graphify Wiki directory."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")


def inspect_wiki_directory(value: str | Path) -> dict[str, object]:
    """Check index presence and local Markdown links without judging content."""

    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError(f"Wiki directory does not exist: {root}")
    pages = sorted(root.rglob("*.md"))
    page_set = {page.resolve() for page in pages}
    inbound = {page: 0 for page in page_set}
    broken: list[dict[str, str]] = []
    local_link_count = 0

    for page in pages:
        try:
            text = page.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Cannot read Wiki page {page}: {exc}") from exc
        for raw_target in _MARKDOWN_LINK_RE.findall(text):
            target = unquote(raw_target).split("#", 1)[0]
            if (
                not target
                or "://" in target
                or target.startswith(("mailto:", "data:"))
            ):
                continue
            local_link_count += 1
            target_path = (page.parent / target).resolve()
            if target_path.is_dir():
                target_path = target_path / "index.md"
            if not target_path.exists():
                broken.append(
                    {
                        "source": str(page.relative_to(root)).replace("\\", "/"),
                        "target": raw_target,
                    }
                )
            elif target_path in inbound:
                inbound[target_path] += 1

    index_path = (root / "index.md").resolve()
    orphan_pages = sorted(
        str(page.relative_to(root)).replace("\\", "/")
        for page, count in inbound.items()
        if page != index_path and count == 0
    )
    return {
        "path": str(root),
        "index_exists": index_path.is_file(),
        "page_count": len(pages),
        "local_link_count": local_link_count,
        "broken_link_count": len(broken),
        "broken_links": broken,
        "orphan_page_count": len(orphan_pages),
        "orphan_pages": orphan_pages,
    }
