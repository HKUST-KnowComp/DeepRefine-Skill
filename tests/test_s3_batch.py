from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "studies"
    / "s3-redocred"
    / "batch.py"
)
SPEC = importlib.util.spec_from_file_location("s3_batch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
s3_batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s3_batch)


def _write_complete_case(root: Path, case_id: str, *, calls: int = 20) -> Path:
    case_dir = root / case_id
    for mode, has_context in (("open", True), ("closed", False)):
        condition_dir = case_dir / mode
        condition_dir.mkdir(parents=True)
        (condition_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "queries_completed": 3,
                    "context": {"passed_to_original_chunk": has_context},
                }
            ),
            encoding="utf-8",
        )
    condition = {
        "usage": {
            "calls": calls,
            "errors": 0,
            "by_kind": {"llm": {"calls": 8}},
        },
        "metrics": {"denominator": 3},
    }
    (case_dir / "summary.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "total_calls": calls * 2,
                "conditions": {"open": condition, "closed": condition},
            }
        ),
        encoding="utf-8",
    )
    return case_dir


def test_validate_completed_case_checks_context_and_usage(tmp_path: Path) -> None:
    case_dir = _write_complete_case(tmp_path, "case-a")

    result = s3_batch.validate_completed_case(case_dir)

    assert result == {
        "case_id": "case-a",
        "calls": 40,
        "llm_calls": 16,
        "open_metrics": {"denominator": 3},
        "closed_metrics": {"denominator": 3},
    }


def test_validate_rejects_incomplete_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "case-a"
    case_dir.mkdir()

    with pytest.raises(s3_batch.BatchGateError, match="incomplete"):
        s3_batch.validate_completed_case(case_dir)


def test_validate_rejects_api_error(tmp_path: Path) -> None:
    case_dir = _write_complete_case(tmp_path, "case-a")
    summary_path = case_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["conditions"]["open"]["usage"]["errors"] = 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(s3_batch.BatchGateError, match="API errors"):
        s3_batch.validate_completed_case(case_dir)


def test_scan_batch_sums_only_valid_completed_cases(tmp_path: Path) -> None:
    _write_complete_case(tmp_path, "case-a", calls=10)
    _write_complete_case(tmp_path, "case-b", calls=15)

    state = s3_batch.scan_batch(tmp_path, ["case-a", "case-b", "case-c"])

    assert state["calls"] == 50
    assert state["llm_calls"] == 32
    assert [row["case_id"] for row in state["completed"]] == ["case-a", "case-b"]
