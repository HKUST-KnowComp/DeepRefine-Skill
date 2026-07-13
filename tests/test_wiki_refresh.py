"""Tests for ``deeprefine apply --refresh-wiki`` staging and rollback."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from deeprefine_skill.cli import main
from deeprefine_skill.wiki_refresh import (
    WikiRefreshError,
    apply_refinement_with_wiki_refresh,
)


def _make_project(
    tmp_path: Path, *, directed: bool = True
) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    out = project / "graphify-out"
    wiki = out / "wiki"
    wiki.mkdir(parents=True)

    graph = out / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "directed": directed,
                "multigraph": False,
                "nodes": [
                    {"id": "a", "label": "Alpha", "community": 0},
                    {"id": "b", "label": "Beta", "community": 0},
                    {"id": "c", "label": "Gamma", "community": 0},
                    {"id": "d", "label": "Delta", "community": 0},
                ],
                "links": [
                    {
                        "source": "a",
                        "target": "b",
                        "relation": "related_to",
                        "confidence": "EXTRACTED",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (wiki / "index.md").write_text("old wiki", encoding="utf-8")
    (wiki / "community-0.md").write_text("old community", encoding="utf-8")
    (out / ".graphify_labels.json").write_text(
        json.dumps({"0": "Core"}), encoding="utf-8"
    )
    return project, graph, wiki


def _graph_hash(graph: Path) -> str:
    return hashlib.sha256(graph.read_bytes()).hexdigest()


def _wiki_snapshot(wiki: Path) -> dict[str, str]:
    return {
        str(path.relative_to(wiki)): path.read_text(encoding="utf-8")
        for path in sorted(wiki.rglob("*"))
        if path.is_file()
    }


def _assert_no_wiki_refresh_temps(graph: Path) -> None:
    temp_parent = graph.parent / ".deeprefine"
    assert not list(temp_parent.glob("wiki-refresh-*"))


def _fake_successful_export(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, *, cwd, env, text, capture_output, check):
        stage_out = Path(env["GRAPHIFY_OUT"])
        staged_graph = Path(command[command.index("--graph") + 1])
        graph_data = json.loads(staged_graph.read_text(encoding="utf-8"))
        stage_wiki = stage_out / "wiki"
        stage_wiki.mkdir()
        (stage_wiki / "index.md").write_text(
            f"wiki generated with {len(graph_data['links'])} links",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "Wiki: ok\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_refresh_commits_graph_and_wiki_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    observed_analysis: dict = {}

    def fake_run(command, *, cwd, env, text, capture_output, check):
        assert command[:3] == ["/fake/graphify", "export", "wiki"]
        assert Path(cwd) == project
        stage_out = Path(env["GRAPHIFY_OUT"])
        staged_graph = Path(command[command.index("--graph") + 1])
        graph_data = json.loads(staged_graph.read_text(encoding="utf-8"))
        observed_analysis.update(
            json.loads(
                (stage_out / ".graphify_analysis.json").read_text(encoding="utf-8")
            )
        )
        stage_wiki = stage_out / "wiki"
        stage_wiki.mkdir()
        label = graph_data["nodes"][0]["label"]
        (stage_wiki / "index.md").write_text(
            f"wiki generated from {label}", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "Wiki: ok\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = apply_refinement_with_wiki_refresh(
        graph_path=graph,
        refinement_text=(
            '<refinement>replace_node("Alpha", "Alpha Updated")</refinement>'
        ),
        project_root=project,
        graphify_executable="/fake/graphify",
    )

    updated = json.loads(graph.read_text(encoding="utf-8"))
    assert updated["nodes"][0]["label"] == "Alpha Updated"
    assert (wiki / "index.md").read_text(encoding="utf-8") == (
        "wiki generated from Alpha Updated"
    )
    assert observed_analysis["communities"] == {"0": ["a", "b", "c", "d"]}
    assert result.changes == ["replace_node(Alpha, Alpha Updated)"]
    assert result.wiki_dir == wiki


def test_refresh_allows_new_edge_for_previously_unrelated_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    _fake_successful_export(monkeypatch)

    result = apply_refinement_with_wiki_refresh(
        graph_path=graph,
        refinement_text=(
            '<refinement>insert_edge("Gamma", "uses", "Delta")</refinement>'
        ),
        project_root=project,
        graphify_executable="/fake/graphify",
    )

    updated = json.loads(graph.read_text(encoding="utf-8"))
    assert any(
        link["source"] == "c" and link["target"] == "d" and link["relation"] == "uses"
        for link in updated["links"]
    )
    assert (wiki / "index.md").read_text(encoding="utf-8") == (
        "wiki generated with 2 links"
    )
    assert result.changes == ["insert_edge(Gamma, uses, Delta)"]
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_does_not_block_historical_parallel_edges_for_unrelated_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    raw = json.loads(graph.read_text(encoding="utf-8"))
    raw["links"].append(
        {
            "source": "a",
            "target": "b",
            "relation": "imports_from",
            "confidence": "EXTRACTED",
        }
    )
    graph.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    _fake_successful_export(monkeypatch)

    result = apply_refinement_with_wiki_refresh(
        graph_path=graph,
        refinement_text=(
            '<refinement>insert_edge("Gamma", "uses", "Delta")</refinement>'
        ),
        project_root=project,
        graphify_executable="/fake/graphify",
    )

    assert result.changes == ["insert_edge(Gamma, uses, Delta)"]
    assert (wiki / "index.md").read_text(encoding="utf-8") == (
        "wiki generated with 3 links"
    )
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_rejects_new_parallel_relation_and_leaves_outputs_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    original_graph_hash = _graph_hash(graph)
    original_wiki = _wiki_snapshot(wiki)
    _fake_successful_export(monkeypatch)

    with pytest.raises(WikiRefreshError, match="parallel relations"):
        apply_refinement_with_wiki_refresh(
            graph_path=graph,
            refinement_text=(
                '<refinement>insert_edge("Alpha", "uses_data_module", "Beta")'
                "</refinement>"
            ),
            project_root=project,
            graphify_executable="/fake/graphify",
        )

    assert _graph_hash(graph) == original_graph_hash
    assert _wiki_snapshot(wiki) == original_wiki
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_rejects_two_new_parallel_relations_in_same_refinement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    original_graph_hash = _graph_hash(graph)
    original_wiki = _wiki_snapshot(wiki)
    _fake_successful_export(monkeypatch)

    with pytest.raises(WikiRefreshError, match="parallel relations"):
        apply_refinement_with_wiki_refresh(
            graph_path=graph,
            refinement_text=(
                '<refinement>insert_edge("Gamma", "uses", "Delta")|'
                'insert_edge("Gamma", "produces", "Delta")</refinement>'
            ),
            project_root=project,
            graphify_executable="/fake/graphify",
        )

    assert _graph_hash(graph) == original_graph_hash
    assert _wiki_snapshot(wiki) == original_wiki
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_rejects_reversed_parallel_relation_when_graph_is_undirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path, directed=False)
    original_graph_hash = _graph_hash(graph)
    original_wiki = _wiki_snapshot(wiki)
    _fake_successful_export(monkeypatch)

    with pytest.raises(WikiRefreshError, match="parallel relations"):
        apply_refinement_with_wiki_refresh(
            graph_path=graph,
            refinement_text=(
                '<refinement>insert_edge("Beta", "uses_data_module", "Alpha")'
                "</refinement>"
            ),
            project_root=project,
            graphify_executable="/fake/graphify",
        )

    assert _graph_hash(graph) == original_graph_hash
    assert _wiki_snapshot(wiki) == original_wiki
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_allows_reversed_relation_when_graph_is_directed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path, directed=True)
    _fake_successful_export(monkeypatch)

    result = apply_refinement_with_wiki_refresh(
        graph_path=graph,
        refinement_text=(
            '<refinement>insert_edge("Beta", "uses_data_module", "Alpha")'
            "</refinement>"
        ),
        project_root=project,
        graphify_executable="/fake/graphify",
    )

    updated = json.loads(graph.read_text(encoding="utf-8"))
    assert any(
        link["source"] == "b"
        and link["target"] == "a"
        and link["relation"] == "uses_data_module"
        for link in updated["links"]
    )
    assert result.changes == ["insert_edge(Beta, uses_data_module, Alpha)"]
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_allows_two_new_reversed_relations_in_same_directed_refinement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path, directed=True)
    _fake_successful_export(monkeypatch)

    result = apply_refinement_with_wiki_refresh(
        graph_path=graph,
        refinement_text=(
            '<refinement>insert_edge("Gamma", "uses", "Delta")|'
            'insert_edge("Delta", "produces", "Gamma")</refinement>'
        ),
        project_root=project,
        graphify_executable="/fake/graphify",
    )

    updated = json.loads(graph.read_text(encoding="utf-8"))
    assert any(
        link["source"] == "c" and link["target"] == "d" and link["relation"] == "uses"
        for link in updated["links"]
    )
    assert any(
        link["source"] == "d"
        and link["target"] == "c"
        and link["relation"] == "produces"
        for link in updated["links"]
    )
    assert result.changes == [
        "insert_edge(Gamma, uses, Delta)",
        "insert_edge(Delta, produces, Gamma)",
    ]
    _assert_no_wiki_refresh_temps(graph)


def test_apply_refresh_wiki_returns_nonzero_for_parallel_relation_without_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    original_graph_hash = _graph_hash(graph)
    original_wiki = _wiki_snapshot(wiki)
    actions = tmp_path / "actions.txt"
    actions.write_text(
        '<refinement>insert_edge("Alpha", "uses_data_module", "Beta")</refinement>',
        encoding="utf-8",
    )
    fake_bin = tmp_path / "graphify"
    fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}")

    code = main(
        [
            "apply",
            "--refresh-wiki",
            "--skip-trace-check",
            "--allow-low-confidence",
            "--refinement-file",
            str(actions),
            "--project-root",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "Graphify Wiki exporter" in captured.err
    assert "parallel relations" in captured.err
    assert _graph_hash(graph) == original_graph_hash
    assert _wiki_snapshot(wiki) == original_wiki
    _assert_no_wiki_refresh_temps(graph)


def test_refresh_failure_leaves_graph_and_wiki_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, graph, wiki = _make_project(tmp_path)
    original_graph = graph.read_text(encoding="utf-8")
    original_wiki = (wiki / "index.md").read_text(encoding="utf-8")

    def fake_run(command, *, cwd, env, text, capture_output, check):
        return subprocess.CompletedProcess(command, 1, "", "export failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WikiRefreshError, match="left unchanged"):
        apply_refinement_with_wiki_refresh(
            graph_path=graph,
            refinement_text=(
                '<refinement>replace_node("Alpha", "Alpha Updated")</refinement>'
            ),
            project_root=project,
            graphify_executable="/fake/graphify",
        )

    assert graph.read_text(encoding="utf-8") == original_graph
    assert (wiki / "index.md").read_text(encoding="utf-8") == original_wiki
