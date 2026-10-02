from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


STUDY_DIR = (
    Path(__file__).resolve().parent.parent / "eval" / "studies" / "s3-redocred"
)
sys.path.insert(0, str(STUDY_DIR))
SPEC = importlib.util.spec_from_file_location("s3_pilot", STUDY_DIR / "pilot.py")
assert SPEC is not None and SPEC.loader is not None
s3_pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s3_pilot)


def test_target_selection_is_deterministic() -> None:
    edges = [
        {"source": "e0", "relation": f"r{index}", "target": f"e{index + 1}"}
        for index in range(10)
    ]
    first = s3_pilot.select_targets("case", edges)
    second = s3_pilot.select_targets("case", list(reversed(edges)))

    assert first == second
    assert len(first) == 3


def test_usage_recorder_enforces_caps_before_request() -> None:
    recorder = s3_pilot.UsageRecorder(call_cap=2, llm_cap=1)
    recorder.before_request("llm")
    recorder.record(kind="llm", model="m", elapsed_s=0.1)

    with pytest.raises(s3_pilot.PilotStopped, match="LLM request cap"):
        recorder.before_request("llm")

    recorder.before_request("embed")
    recorder.record(kind="embed", model="e", elapsed_s=0.1)
    with pytest.raises(s3_pilot.PilotStopped, match="request cap"):
        recorder.before_request("embed")


def test_usage_recorder_stops_after_first_error() -> None:
    recorder = s3_pilot.UsageRecorder(call_cap=10, llm_cap=10)
    recorder.record(kind="embed", model="e", elapsed_s=0.1, error="Timeout")

    with pytest.raises(s3_pilot.PilotStopped, match="earlier API request failed"):
        recorder.before_request("embed")


def test_target_metrics_keeps_strict_and_endpoint_separate() -> None:
    target = {"source": "e0", "relation": "gold", "target": "e1"}
    evaluation = {
        "cases": [
            {
                "baseline": {
                    "missing_edges": [target],
                    "spurious_edges": [],
                },
                "candidate": {
                    "missing_edges": [target],
                    "spurious_edges": [
                        {"source": "e0", "relation": "wrong", "target": "e1"}
                    ],
                },
            }
        ]
    }

    metrics = s3_pilot.target_metrics(
        evaluation,
        targets=[target],
        gold_edges=[target],
    )

    assert metrics["strict_relation_label"] == 0
    assert metrics["endpoint_pair_added"] == 1
    assert metrics["denominator"] == 1


def test_exact_entity_fold_rehomes_edge_without_rewriting_relation() -> None:
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_node("baseline-film", id="Film")
    graph.add_node("phantom-film", id="Film")
    graph.add_node("new-year", id="1999")
    graph.add_edge("phantom-film", "new-year", relation="release_year")

    report = s3_pilot.fold_exact_baseline_entities(
        graph,
        {"baseline-film": "Film"},
    )

    assert "phantom-film" not in graph
    assert graph.has_edge("baseline-film", "new-year")
    assert graph.edges["baseline-film", "new-year"]["relation"] == "release_year"
    assert report["edges_remapped"] == 1
    assert report["folded"]["phantom-film"]["target"] == "baseline-film"


def test_exact_entity_fold_keeps_ambiguous_match() -> None:
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_node("baseline-a", id="Iran")
    graph.add_node("baseline-b", id="Iran")
    graph.add_node("phantom", id="Iran")

    report = s3_pilot.fold_exact_baseline_entities(
        graph,
        {"baseline-a": "Iran", "baseline-b": "Iran"},
    )

    assert "phantom" in graph
    assert report["residual"] == [
        {"key": "phantom", "label": "Iran", "reason": "ambiguous"}
    ]
