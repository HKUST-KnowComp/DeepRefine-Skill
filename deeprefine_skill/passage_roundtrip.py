"""Preserve existing passage nodes across graphify write-back.

DeepRefine excludes passage nodes from its working entity graph. Rebuilding
``graph.json`` solely from that graph would therefore drop passages that were
present in the input. These helpers snapshot those nodes before the rebuild
and append them afterwards without generating new passages or changing links.
"""

from __future__ import annotations

import copy
from typing import Any


def snapshot_passages(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return independent copies of all existing ``type=passage`` nodes."""
    return [
        copy.deepcopy(node)
        for node in raw.get("nodes", [])
        if node.get("type") == "passage"
    ]


def merge_passages(
    output: dict[str, Any], passages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Append preserved passages unless the rebuilt graph already owns the id.

    A rebuilt entity wins an id collision. This avoids creating duplicate node
    ids while keeping ordinary passage dictionaries byte-for-byte equivalent.
    """
    if not passages:
        return output
    existing_ids = {node.get("id") for node in output.get("nodes", [])}
    nodes = output.setdefault("nodes", [])
    for passage in passages:
        passage_id = passage.get("id")
        if passage_id in existing_ids:
            continue
        nodes.append(copy.deepcopy(passage))
        existing_ids.add(passage_id)
    return output
