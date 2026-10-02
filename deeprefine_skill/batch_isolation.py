"""Per-query failure isolation for batch refinement."""

from __future__ import annotations

from typing import Any


def run_query_isolated(
    engine: Any, query: str
) -> tuple[tuple[Any, Any, Any] | None, str | None]:
    """Run one query and restore its starting graph when it raises.

    A refinement call may mutate the working graph before malformed model
    output or another downstream error is raised. Restoring the snapshot keeps
    a failed query from contaminating later queries or the persisted batch.
    """
    graph_before = engine.kg.copy()
    try:
        return engine.refine(query=query), None
    except Exception as exc:  # noqa: BLE001 - isolation is the public contract
        engine.kg = graph_before
        return None, f"{type(exc).__name__}: {exc}"
