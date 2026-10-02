from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_protocol() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "eval"
        / "studies"
        / "s4-2wiki"
        / "protocol.py"
    )
    spec = importlib.util.spec_from_file_location("s4_protocol", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = _load_protocol()


def _graph(path: Path, *, links: list[dict] | None = None) -> None:
    path.write_text(
        json.dumps({"nodes": [{"id": "a"}, {"id": "b"}], "links": links or []}),
        encoding="utf-8",
    )


def test_corrected_timeline_uses_candidate_only_after_action_and_new_reader(tmp_path):
    baseline = tmp_path / "frozen.json"
    _graph(baseline)
    calls = []

    def fake_phase(request):
        calls.append(request)
        before = protocol.sha256_file(request.graph_path)
        if request.phase == "refinement":
            payload = json.loads(request.graph_path.read_text(encoding="utf-8"))
            payload["links"].append(
                {"source": "a", "target": "b", "relation": "corrected"}
            )
            request.graph_path.write_text(json.dumps(payload), encoding="utf-8")
            return protocol.PhaseResult(
                phase=request.phase,
                source="refinement",
                graph_hash_before=before,
                graph_hash_after=protocol.sha256_file(request.graph_path),
                process_id=202,
                instance_id="refiner-1",
                action_count=1,
                # This value must never become the post answer.
                answer="answer from refinement history",
            )
        answer = "pre from frozen" if request.phase == "baseline-reader" else "post from candidate"
        return protocol.PhaseResult(
            phase=request.phase,
            source="reader",
            graph_hash_before=before,
            graph_hash_after=protocol.sha256_file(request.graph_path),
            process_id=101 if request.phase == "baseline-reader" else 303,
            instance_id="reader-pre" if request.phase == "baseline-reader" else "reader-post",
            answer=answer,
            reader_config=request.reader_config,
            index_rebuilt=True,
        )

    config = protocol.ReaderConfig(model="fixed-llm", embedding_model="fixed-emb")
    result = protocol.execute_case(
        case_id="case-1",
        question="Who?",
        baseline_graph=baseline,
        case_root=tmp_path / "run" / "case-1",
        reader_config=config,
        run_phase=fake_phase,
    )

    assert [call.phase for call in calls] == [
        "baseline-reader",
        "refinement",
        "post-reader",
    ]
    assert calls[0].reader_config == calls[2].reader_config == config
    assert calls[0].rebuild_index and calls[2].rebuild_index
    assert calls[0].read_only and calls[2].read_only
    assert calls[0].sandbox != calls[1].sandbox != calls[2].sandbox
    assert result.pre_answer == "pre from frozen"
    assert result.post_answer == "post from candidate"
    assert result.post_answer != "answer from refinement history"
    assert result.baseline_graph_hash != result.candidate_graph_hash
    assert result.graph_diff_summary["links_added"] == 1
    assert result.graph_diff_summary["links_removed"] == 0
    assert protocol.sha256_file(baseline) == result.baseline_graph_hash


def test_reader_graph_write_is_rejected(tmp_path):
    baseline = tmp_path / "frozen.json"
    _graph(baseline)

    def mutating_reader(request):
        before = protocol.sha256_file(request.graph_path)
        request.graph_path.write_text("{}", encoding="utf-8")
        return protocol.PhaseResult(
            phase=request.phase,
            source="reader",
            graph_hash_before=before,
            graph_hash_after=protocol.sha256_file(request.graph_path),
            process_id=1,
            instance_id="bad-reader",
            answer="bad",
            reader_config=request.reader_config,
            index_rebuilt=True,
        )

    try:
        protocol.execute_case(
            case_id="case-1",
            question="Who?",
            baseline_graph=baseline,
            case_root=tmp_path / "run" / "case-1",
            reader_config=protocol.ReaderConfig(
                model="fixed-llm", embedding_model="fixed-emb"
            ),
            run_phase=mutating_reader,
        )
    except protocol.ProtocolViolation as exc:
        assert "reader modified its graph" in str(exc)
    else:
        raise AssertionError("mutating reader was accepted")


def test_refinement_result_cannot_be_used_as_post_reader(tmp_path):
    graph = tmp_path / "graph.json"
    _graph(graph)
    request = protocol.PhaseRequest(
        phase="post-reader",
        case_id="case-1",
        question="Who?",
        graph_path=graph,
        sandbox=tmp_path,
        rebuild_index=True,
        read_only=True,
        reader_config=protocol.ReaderConfig(
            model="fixed-llm", embedding_model="fixed-emb"
        ),
    )
    graph_hash = protocol.sha256_file(graph)
    result = protocol.PhaseResult(
        phase="post-reader",
        source="refinement",
        graph_hash_before=graph_hash,
        graph_hash_after=graph_hash,
        process_id=2,
        instance_id="refiner",
        answer="last interaction_history answer",
        reader_config=request.reader_config,
        index_rebuilt=True,
    )

    try:
        protocol._validate_phase_result(request, result)
    except protocol.ProtocolViolation as exc:
        assert "independent reader run" in str(exc)
    else:
        raise AssertionError("refinement answer was accepted as post-reader output")


def test_zero_action_identical_graph_requires_same_answer(tmp_path):
    baseline = tmp_path / "frozen.json"
    _graph(baseline)

    def unstable_phase(request):
        graph_hash = protocol.sha256_file(request.graph_path)
        reader = request.phase != "refinement"
        return protocol.PhaseResult(
            phase=request.phase,
            source="reader" if reader else "refinement",
            graph_hash_before=graph_hash,
            graph_hash_after=graph_hash,
            process_id={"baseline-reader": 1, "refinement": 2, "post-reader": 3}[
                request.phase
            ],
            instance_id=request.phase,
            answer=(
                "answer-a"
                if request.phase == "baseline-reader"
                else "answer-b" if request.phase == "post-reader" else None
            ),
            action_count=0,
            reader_config=request.reader_config if reader else None,
            index_rebuilt=reader,
        )

    try:
        protocol.execute_case(
            case_id="case-1",
            question="Who?",
            baseline_graph=baseline,
            case_root=tmp_path / "run" / "case-1",
            reader_config=protocol.ReaderConfig(
                model="fixed-llm", embedding_model="fixed-emb"
            ),
            run_phase=unstable_phase,
        )
    except protocol.ProtocolViolation as exc:
        assert "zero-action identical graphs" in str(exc)
    else:
        raise AssertionError("unstable zero-action comparison was accepted")
