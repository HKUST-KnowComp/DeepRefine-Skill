from __future__ import annotations

import json
from pathlib import Path

from deeprefine_skill.cli import main
from deeprefine_skill.paths import (
    clear_rollback_derivatives,
    rollback_derivatives,
)


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    out = project / "graphify-out"
    deep = out / ".deeprefine"
    deep.mkdir(parents=True)

    graph = out / "graph.json"
    graph.write_text('{"nodes": ["post"]}', encoding="utf-8")
    pre_state = deep / "graph.json.bak.1"
    pre_state.write_text('{"nodes": ["pre"]}', encoding="utf-8")
    checkpoint = deep / "checkpoints" / "graph.checkpoint.1.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text('{"nodes": ["post"]}', encoding="utf-8")
    (deep / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "seq": 1,
                    "query_id": "sq-000",
                    "query_text": "question",
                    "ts": "2026-10-02T00:00:00Z",
                    "path": str(checkpoint),
                }
            ]
        ),
        encoding="utf-8",
    )
    (deep / "history.jsonl").write_text(
        json.dumps({"id": "sq-000", "refined": True}) + "\n",
        encoding="utf-8",
    )
    (deep / "proposed_refinement_actions_sq-000.txt").write_text(
        "old proposal", encoding="utf-8"
    )
    (deep / "proposed_refinement_review_sq-000.md").write_text(
        "old review", encoding="utf-8"
    )
    (deep / "proposed_refinement_review_sq-000.json").write_text(
        "{}", encoding="utf-8"
    )
    (deep / "proposed_refinement_review.md").write_text(
        "old singleton review", encoding="utf-8"
    )
    cache = deep / "cache"
    cache.mkdir()
    (cache / "deeprefine_data.pkl").write_bytes(b"newer all-scope bundle")
    (cache / "deeprefine_data-code.pkl").write_bytes(b"newer code-scope bundle")
    (cache / "unrelated.txt").write_text("keep", encoding="utf-8")
    return project, graph, pre_state


def test_derivative_inventory_is_scoped_and_sorted(tmp_path: Path) -> None:
    project, _graph, _pre_state = _make_project(tmp_path)

    proposals, bundles = rollback_derivatives(project)

    assert [path.name for path in proposals] == [
        "proposed_refinement_actions_sq-000.txt",
        "proposed_refinement_review.md",
        "proposed_refinement_review_sq-000.json",
        "proposed_refinement_review_sq-000.md",
    ]
    assert [path.name for path in bundles] == [
        "deeprefine_data-code.pkl",
        "deeprefine_data.pkl",
    ]


def test_cleanup_is_scoped_and_idempotent(tmp_path: Path) -> None:
    project, _graph, _pre_state = _make_project(tmp_path)
    deep = project / "graphify-out" / ".deeprefine"

    assert clear_rollback_derivatives(project) == (4, 2)
    assert clear_rollback_derivatives(project) == (0, 0)
    assert (deep / "history.jsonl").is_file()
    assert (deep / "cache" / "unrelated.txt").is_file()
    assert (deep / "checkpoints" / "graph.checkpoint.1.json").is_file()


def test_rollback_by_query_restores_and_invalidates_derivatives(
    tmp_path: Path, capsys
) -> None:
    project, graph, pre_state = _make_project(tmp_path)

    rc = main(["rollback", "--query", "sq-000", "--project-root", str(project)])

    assert rc == 0
    assert graph.read_text(encoding="utf-8") == pre_state.read_text(encoding="utf-8")
    assert clear_rollback_derivatives(project) == (0, 0)
    output = capsys.readouterr().out
    assert "Cleared 4 stale proposal/review file(s)." in output
    assert "Cleared 2 stale index bundle(s)" in output


def test_rollback_to_checkpoint_invalidates_derivatives(
    tmp_path: Path, capsys
) -> None:
    project, _graph, _pre_state = _make_project(tmp_path)

    rc = main(["rollback", "1", "--project-root", str(project)])

    assert rc == 0
    assert clear_rollback_derivatives(project) == (0, 0)
    output = capsys.readouterr().out
    assert "Cleared 4 stale proposal/review file(s)." in output
    assert "Cleared 2 stale index bundle(s)" in output


def test_failed_rollback_does_not_clear_derivatives(tmp_path: Path) -> None:
    project, _graph, _pre_state = _make_project(tmp_path)

    rc = main(["rollback", "99", "--project-root", str(project)])

    assert rc == 1
    proposals, bundles = rollback_derivatives(project)
    assert len(proposals) == 4
    assert len(bundles) == 2
