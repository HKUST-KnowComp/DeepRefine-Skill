from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "studies"
    / "s4-2wiki"
    / "aggregate.py"
)
SPEC = importlib.util.spec_from_file_location("s4_aggregate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
s4_aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s4_aggregate)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite = tmp_path / "suite.json"
    batch = tmp_path / "batch"
    case_id = "2wiki-case"
    _write(
        suite,
        {
            "suite_id": "2wiki-mini-v1",
            "cases": [
                {"id": case_id, "answers": ["after"], "question_type": "comparison"}
            ],
        },
    )
    config = {"model": "fixed", "seed": 2026}
    case = batch / "cases" / case_id
    _write(
        case / "protocol-result.json",
        {
            "case_id": case_id,
            "pre_answer": "before",
            "post_answer": "after",
            "baseline_graph_hash": "baseline",
            "candidate_graph_hash": "candidate",
            "action_count": 1,
            "reader_config": config,
        },
    )
    phases = {
        "baseline-reader": {
            "process_id": 1,
            "instance_id": "pre",
            "graph_hash_before": "baseline",
            "graph_hash_after": "baseline",
            "reader_config": config,
            "index_rebuilt": True,
        },
        "refinement": {
            "process_id": 2,
            "instance_id": "refine",
            "graph_hash_before": "baseline",
            "graph_hash_after": "candidate",
            "action_count": 1,
        },
        "post-reader": {
            "process_id": 3,
            "instance_id": "post",
            "graph_hash_before": "candidate",
            "graph_hash_after": "candidate",
            "reader_config": config,
            "index_rebuilt": True,
        },
    }
    for name, phase in phases.items():
        _write(case / name / "phase-result.json", phase)
        (case / name / "api-usage.jsonl").write_text(
            json.dumps(
                {
                    "record_type": "detail",
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "error": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
    _write(
        batch / "batch-manifest.json",
        {
            "status": "complete",
            "completed_case_ids": [case_id],
            "calls": 3,
        },
    )
    return suite, batch


def test_aggregate_validates_protocol_and_compacts(tmp_path: Path) -> None:
    suite, batch = _fixture(tmp_path)

    report = s4_aggregate.aggregate(suite, batch, 1)

    assert report["overall"]["em_before"] == 0.0
    assert report["overall"]["em_after"] == 1.0
    assert report["protocol_validation"]["action_count"] == 1
    assert report["protocol_validation"]["reader_config_count"] == 1
    assert report["reader_config"] == {"model": "fixed", "seed": 2026}
    assert "cases" not in s4_aggregate.compact_report(report)


def test_aggregate_rejects_reader_config_drift(tmp_path: Path) -> None:
    suite, batch = _fixture(tmp_path)
    phase_path = batch / "cases" / "2wiki-case" / "post-reader" / "phase-result.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["reader_config"]["seed"] = 2027
    _write(phase_path, phase)

    try:
        s4_aggregate.aggregate(suite, batch, 1)
    except ValueError as exc:
        assert "configuration mismatch" in str(exc)
    else:
        raise AssertionError("reader configuration drift was accepted")
