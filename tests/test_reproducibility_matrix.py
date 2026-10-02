import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "eval" / "reports" / "reproducibility-matrix.json"


def test_reproducibility_matrix_has_all_stages_and_local_safe_paths() -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    stages = payload["stages"]

    assert [stage["stage"] for stage in stages] == [
        "s1-code-single",
        "s2-code-multirepo",
        "s3-redocred",
        "s4-2wiki",
    ]
    serialized = json.dumps(payload)
    assert "/Users/" not in serialized
    assert "docs/tmp" not in serialized


def test_completed_stage_results_are_tracked_and_pending_stage_is_explicit() -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    by_stage = {stage["stage"]: stage for stage in payload["stages"]}

    for name in ("s1-code-single", "s2-code-multirepo", "s3-redocred"):
        result = by_stage[name]["result"]
        assert result is not None
        assert (ROOT / result).is_file()

    assert by_stage["s4-2wiki"]["status"] == "complete"
    assert (ROOT / by_stage["s4-2wiki"]["result"]).is_file()
