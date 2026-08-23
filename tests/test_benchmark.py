"""Public-contract tests for the lightweight benchmark CLI.

The bundled synthetic suite is deliberately tiny.  It validates the evaluator
and report plumbing without downloading or redistributing third-party data.
"""

from __future__ import annotations

import json
from pathlib import Path

import deeprefine_skill
import pytest

from deeprefine_skill.benchmarking.graph import (
    GraphNode,
    align_entities,
    bounded_bfs,
    load_graphify_graph,
    normalize_source,
)
from deeprefine_skill.benchmarking.evaluator import evaluate_suite
from deeprefine_skill.benchmarking.metrics import (
    answer_exact_match,
    answer_token_f1,
    lexical_graph_score,
    precision_recall_f1,
    reciprocal_rank,
)
from deeprefine_skill.benchmarking.prepare import prepare_suite
from deeprefine_skill.benchmarking.suite import sha256_file, verify_suite_lock
from deeprefine_skill.benchmarking.wiki import inspect_wiki_directory
from deeprefine_skill.cli import main


PACKAGE_ROOT = Path(deeprefine_skill.__file__).resolve().parent
SMOKE_SUITE_DIR = (
    PACKAGE_ROOT / "benchmark_suites" / "synthetic-smoke-v1"
)
SMOKE_SUITE = SMOKE_SUITE_DIR / "suite.json"
BASELINE_GRAPH = SMOKE_SUITE_DIR / "baseline_graph.json"
CANDIDATE_GRAPH = SMOKE_SUITE_DIR / "candidate_graph.json"
BASELINE_PREDICTIONS = SMOKE_SUITE_DIR / "baseline_predictions.jsonl"
CANDIDATE_PREDICTIONS = SMOKE_SUITE_DIR / "candidate_predictions.jsonl"


def _run_smoke_evaluation(output_dir: Path, *, predictions: bool = False) -> int:
    args = [
        "benchmark",
        "evaluate",
        "--suite",
        str(SMOKE_SUITE),
        "--baseline-graph",
        str(BASELINE_GRAPH),
        "--candidate-graph",
        str(CANDIDATE_GRAPH),
        "--output-dir",
        str(output_dir),
    ]
    if predictions:
        args.extend(
            [
                "--baseline-predictions",
                str(BASELINE_PREDICTIONS),
                "--candidate-predictions",
                str(CANDIDATE_PREDICTIONS),
            ]
        )
    return main(args)


def test_benchmark_help_lists_public_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "prepare" in output
    assert "evaluate" in output
    assert "report" in output


def test_packaged_synthetic_suite_uses_versioned_public_schema() -> None:
    assert SMOKE_SUITE.is_file()
    assert BASELINE_GRAPH.is_file()
    assert CANDIDATE_GRAPH.is_file()

    suite = json.loads(SMOKE_SUITE.read_text(encoding="utf-8"))
    assert suite["schema_version"] == 1
    assert suite["suite_id"] == "synthetic-smoke-v1"
    assert suite["suite_version"]
    assert suite["profile"] == "smoke"
    assert suite["source"]
    assert suite["cases"]

    tasks = {case["task"] for case in suite["cases"]}
    assert tasks == {"intrinsic", "downstream"}
    for case in suite["cases"]:
        assert case["id"]
        if case["task"] == "intrinsic":
            assert case["source_files"]
            assert case["gold_entities"]
            assert case["gold_edges"]
        else:
            assert case["question"]
            assert case["answers"]
            assert case["seed_entities"]
            assert case["answer_entities"]
            assert case["evidence_edges"]
            assert case["max_hops"] >= 1


def test_benchmark_evaluate_writes_json_and_markdown(tmp_path: Path) -> None:
    output_dir = tmp_path / "evaluation"

    exit_code = _run_smoke_evaluation(output_dir)

    assert exit_code == 0
    result_path = output_dir / "result.json"
    report_path = output_dir / "report.md"
    assert result_path.is_file()
    assert report_path.is_file()

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    before = result["metrics"]["baseline"]
    after = result["metrics"]["candidate"]
    assert before["intrinsic"]["macro"]["strict_triple_f1"] < 1.0
    assert after["intrinsic"]["macro"]["strict_triple_f1"] == pytest.approx(1.0)
    assert before["downstream"]["macro"]["complete_path_rate"] == pytest.approx(0.25)
    assert after["downstream"]["macro"]["complete_path_rate"] == pytest.approx(1.0)

    report = report_path.read_text(encoding="utf-8")
    assert "synthetic" in report.lower()
    assert "baseline" in report.lower()
    assert "candidate" in report.lower()


def test_benchmark_evaluate_accepts_optional_predictions(tmp_path: Path) -> None:
    assert BASELINE_PREDICTIONS.is_file()
    assert CANDIDATE_PREDICTIONS.is_file()
    output_dir = tmp_path / "evaluation-with-predictions"

    exit_code = _run_smoke_evaluation(output_dir, predictions=True)

    assert exit_code == 0
    result = json.loads(
        (output_dir / "result.json").read_text(encoding="utf-8")
    )
    serialized = json.dumps(result, sort_keys=True).lower()
    assert "answer" in serialized
    assert (
        result["metrics"]["candidate"]["downstream"]["prediction"]["answer_f1"]["value"]
        == pytest.approx(1.0)
    )


def test_benchmark_report_renders_an_existing_result(tmp_path: Path) -> None:
    evaluation_dir = tmp_path / "evaluation"
    assert _run_smoke_evaluation(evaluation_dir, predictions=True) == 0
    output = tmp_path / "combined-report.md"

    exit_code = main(
        [
            "benchmark",
            "report",
            "--result",
            str(evaluation_dir / "result.json"),
            "--format",
            "markdown",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.is_file()
    rendered = output.read_text(encoding="utf-8")
    assert "synthetic" in rendered.lower()
    assert "baseline" in rendered.lower()
    assert "candidate" in rendered.lower()


def test_graph_loader_preserves_parallel_relations_and_diagnostics() -> None:
    graph = load_graphify_graph(
        {
            "directed": False,
            "multigraph": True,
            "nodes": [
                {"id": "a", "label": "Ａlpha", "aliases": ["Alpha"]},
                {"id": "b", "label": "Beta"},
            ],
            "edges": [
                {"source": "a", "target": "b", "relation": "calls"},
                {"source": "a", "target": "b", "relation": "imports"},
                {"source": "b", "target": "a", "relation": "calls"},
                {"source": "a", "target": "missing", "relation": "calls"},
                {"source": "a", "target": "a", "relation": "self"},
            ],
        }
    )

    assert len(graph.edges) == 4
    assert graph.diagnostics["duplicate_edges"] == 1
    assert graph.diagnostics["dangling_edges"] == 1
    assert graph.diagnostics["self_loops"] == 1
    assert graph.node_ids_for_aliases(["alpha"]) == ["a"]
    assert bounded_bfs(graph, ["b"], 1)["a"] == 1


def test_entity_alignment_uses_alias_and_source_path() -> None:
    predicted = load_graphify_graph(
        {
            "nodes": [
                {
                    "id": "one",
                    "label": "main()",
                    "source_file": "src/first.py",
                },
                {
                    "id": "two",
                    "label": "main()",
                    "source_file": "src/second.py",
                },
            ],
            "links": [],
        }
    )
    gold = [
        GraphNode("g1", "MAIN()", source_file="first.py"),
        GraphNode("g2", "main()", source_file="second.py"),
    ]

    assert align_entities(gold, predicted) == {"g1": "one", "g2": "two"}
    assert normalize_source(r".\SRC\first.py") == "src/first.py"


def test_metric_primitives_are_hand_checkable() -> None:
    score = precision_recall_f1(2, 1, 2)
    assert score.precision == pytest.approx(2 / 3)
    assert score.recall == pytest.approx(1 / 2)
    assert score.f1 == pytest.approx(4 / 7)
    assert precision_recall_f1(0, 0, 0).f1 == 1.0

    identical = lexical_graph_score(
        ["alpha; located in; beta"],
        ["alpha; located in; beta"],
        metric="rouge",
    )
    mismatch = lexical_graph_score(
        ["alpha; located in; beta"],
        ["gamma; created; delta"],
        metric="rouge",
    )
    assert identical["f1"] == pytest.approx(1.0)
    assert mismatch["f1"] < identical["f1"]

    assert answer_exact_match("The Orion-Database!", ["orion database"]) == 1.0
    assert answer_token_f1("Orion Database", ["the Orion Database"]) == 1.0
    assert reciprocal_rank(["wrong", "answer"], ["answer"]) == 0.5


def test_suite_lock_and_input_graphs_are_unchanged(tmp_path: Path) -> None:
    verify_suite_lock(SMOKE_SUITE_DIR)
    baseline_before = sha256_file(BASELINE_GRAPH)
    candidate_before = sha256_file(CANDIDATE_GRAPH)

    assert _run_smoke_evaluation(tmp_path / "read-only") == 0

    assert sha256_file(BASELINE_GRAPH) == baseline_before
    assert sha256_file(CANDIDATE_GRAPH) == candidate_before


def test_repeated_evaluation_is_deterministic_except_runtime() -> None:
    first = evaluate_suite(
        SMOKE_SUITE,
        BASELINE_GRAPH,
        CANDIDATE_GRAPH,
        baseline_predictions=BASELINE_PREDICTIONS,
        candidate_predictions=CANDIDATE_PREDICTIONS,
    )
    second = evaluate_suite(
        SMOKE_SUITE,
        BASELINE_GRAPH,
        CANDIDATE_GRAPH,
        baseline_predictions=BASELINE_PREDICTIONS,
        candidate_predictions=CANDIDATE_PREDICTIONS,
    )
    first.pop("runtime")
    second.pop("runtime")

    assert first == second


def test_empty_ranked_predictions_are_scored_as_zero(tmp_path: Path) -> None:
    predictions = tmp_path / "empty.jsonl"
    predictions.write_text(
        "\n".join(
            json.dumps(
                {
                    "case_id": f"qa-{index:02d}",
                    "answer": "",
                    "retrieved_nodes": [],
                    "retrieved_supporting_facts": [],
                }
            )
            for index in range(1, 9)
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_suite(
        SMOKE_SUITE,
        BASELINE_GRAPH,
        CANDIDATE_GRAPH,
        baseline_predictions=predictions,
        candidate_predictions=predictions,
    )
    prediction = result["metrics"]["baseline"]["downstream"]["prediction"]

    assert prediction["hit_at_5"]["value"] == 0.0
    assert prediction["mrr"]["value"] == 0.0
    assert prediction["supporting_fact_recall_at_5"]["value"] == 0.0


def test_prepare_copies_builtin_smoke_suite(tmp_path: Path) -> None:
    destination = prepare_suite(
        "synthetic-smoke-v1",
        "smoke",
        tmp_path / "prepared",
    )

    assert (destination / "suite.json").is_file()
    assert (destination / "corpus" / "doc-alpha.txt").is_file()
    verify_suite_lock(destination)


def test_cli_prepare_defaults_synthetic_to_smoke(tmp_path: Path) -> None:
    destination = tmp_path / "cli-prepared"

    assert (
        main(
            [
                "benchmark",
                "prepare",
                "--suite",
                "synthetic-smoke-v1",
                "--output-dir",
                str(destination),
            ]
        )
        == 0
    )
    suite = json.loads((destination / "suite.json").read_text(encoding="utf-8"))
    assert suite["profile"] == "smoke"


def test_suite_lock_rejects_tampered_fixture(tmp_path: Path) -> None:
    destination = prepare_suite(
        "synthetic-smoke-v1",
        "smoke",
        tmp_path / "tampered",
    )
    (destination / "corpus" / "doc-alpha.txt").write_text(
        "tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_suite_lock(destination)


def test_prepare_redocred_quick_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "dev_revised.json"
    documents = [
        {
            "title": f"Document {index}",
            "sents": [["Entity", str(index), "links", "Target"]],
            "vertexSet": [
                [{"name": f"Entity {index}", "sent_id": 0}],
                [{"name": f"Target {index}", "sent_id": 0}],
            ],
            "labels": [{"h": 0, "t": 1, "r": "P17"}],
        }
        for index in range(10)
    ]
    source.write_text(json.dumps(documents), encoding="utf-8")

    first = prepare_suite(
        "redocred-mini-v1",
        "quick",
        tmp_path / "first",
        source=source,
    )
    second = prepare_suite(
        "redocred-mini-v1",
        "quick",
        tmp_path / "second",
        source=source,
    )

    assert (first / "suite.json").read_bytes() == (second / "suite.json").read_bytes()
    suite = json.loads((first / "suite.json").read_text(encoding="utf-8"))
    assert len(suite["cases"]) == 10
    assert all(case["task"] == "intrinsic" for case in suite["cases"])
    verify_suite_lock(first)


def test_prepare_2wiki_quick_is_balanced_and_keeps_distractors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "2wiki.json"
    examples = []
    question_types = (
        "compositional",
        "comparison",
        "inference",
        "bridge_comparison",
    )
    context = [
        [f"Passage {index}", [f"Distractor or evidence sentence {index}."]]
        for index in range(10)
    ]
    for question_type in question_types:
        for index in range(4):
            examples.append(
                {
                    "_id": f"{question_type}-{index}",
                    "type": question_type,
                    "question": f"Question {question_type} {index}?",
                    "answer": "Answer Entity",
                    "context": context,
                    "supporting_facts": [["Passage 0", 0], ["Passage 1", 0]],
                    "evidences": [
                        ["Seed Entity", "links to", "Bridge Entity"],
                        ["Bridge Entity", "answers with", "Answer Entity"],
                    ],
                }
            )
    source.write_text(json.dumps(examples), encoding="utf-8")

    destination = prepare_suite(
        "2wiki-mini-v1",
        "quick",
        tmp_path / "prepared-2wiki",
        source=source,
    )

    suite = json.loads((destination / "suite.json").read_text(encoding="utf-8"))
    assert len(suite["cases"]) == 16
    assert {
        question_type: sum(
            case["question_type"] == question_type for case in suite["cases"]
        )
        for question_type in question_types
    } == {question_type: 4 for question_type in question_types}
    assert len(list((destination / "corpus").glob("*.txt"))) == 10
    assert all(len(case["evidence_edges"]) == 2 for case in suite["cases"])
    verify_suite_lock(destination)


def test_wiki_integrity_check_distinguishes_broken_and_orphan_pages(
    tmp_path: Path,
) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text(
        "[Entity](entity.md)\n[Missing](missing.md)\n",
        encoding="utf-8",
    )
    (wiki / "entity.md").write_text("[Home](index.md)\n", encoding="utf-8")
    (wiki / "orphan.md").write_text("No incoming links.\n", encoding="utf-8")

    result = inspect_wiki_directory(wiki)

    assert result["index_exists"] is True
    assert result["broken_link_count"] == 1
    assert result["orphan_pages"] == ["orphan.md"]


def test_invalid_graph_returns_nonzero_without_partial_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"nodes": []}', encoding="utf-8")
    output = tmp_path / "invalid-output"

    exit_code = main(
        [
            "benchmark",
            "evaluate",
            "--suite",
            str(SMOKE_SUITE),
            "--baseline-graph",
            str(invalid),
            "--candidate-graph",
            str(CANDIDATE_GRAPH),
            "--output-dir",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "links" in captured.err or "edges" in captured.err
    assert not (output / "result.json").exists()


def test_readme_smoke_table_matches_measured_values() -> None:
    result = evaluate_suite(
        SMOKE_SUITE,
        BASELINE_GRAPH,
        CANDIDATE_GRAPH,
        baseline_predictions=BASELINE_PREDICTIONS,
        candidate_predictions=CANDIDATE_PREDICTIONS,
    )
    readme = (PACKAGE_ROOT.parent / "README.md").read_text(encoding="utf-8")
    before = result["metrics"]["baseline"]
    after = result["metrics"]["candidate"]
    expected_rows = (
        (
            "Entity F1",
            before["intrinsic"]["macro"]["entity_f1"],
            after["intrinsic"]["macro"]["entity_f1"],
        ),
        (
            "Strict Triple F1",
            before["intrinsic"]["macro"]["strict_triple_f1"],
            after["intrinsic"]["macro"]["strict_triple_f1"],
        ),
        (
            "Evidence Edge Recall",
            before["downstream"]["macro"]["evidence_edge_recall"],
            after["downstream"]["macro"]["evidence_edge_recall"],
        ),
        (
            "Complete Path Rate",
            before["downstream"]["macro"]["complete_path_rate"],
            after["downstream"]["macro"]["complete_path_rate"],
        ),
    )
    for label, baseline, candidate in expected_rows:
        delta = candidate - baseline
        row = (
            f"| synthetic-smoke-v1 | {label} | {baseline * 100:.2f}% | "
            f"{candidate * 100:.2f}% | {delta * 100:+.2f} pp |"
        )
        assert row in readme
