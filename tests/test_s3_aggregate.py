import json
import sys
from pathlib import Path


STUDY_DIR = Path(__file__).resolve().parents[1] / "eval" / "studies" / "s3-redocred"
sys.path.insert(0, str(STUDY_DIR))

from aggregate import aggregate  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_case(root: Path) -> None:
    case = root / "redocred-case"
    targets = [
        {"source": "e1", "relation": "r1", "target": "e2"},
        {"source": "e3", "relation": "r2", "target": "e4"},
        {"source": "e5", "relation": "r3", "target": "e6"},
    ]
    conditions = {}
    for mode in ("open", "closed"):
        mode_targets = []
        for index, target in enumerate(targets):
            row = dict(target)
            row["strict_recovered"] = False
            row["endpoint_pair_added"] = index == (0 if mode == "open" else 1)
            mode_targets.append(row)
        conditions[mode] = {
            "metrics": {
                "denominator": 3,
                "strict_relation_label": 0,
                "endpoint_pair_added": 1,
                "targets": mode_targets,
            }
        }
        has_context = mode == "open"
        _write_json(
            case / mode / "metadata.json",
            {
                "graph_sha256": "same",
                "context": {
                    "passed_to_original_chunk": has_context,
                    "original_chunk_chars": 10 if has_context else 0,
                    "selected_sha256": "source",
                    "truncation": {"truncated": False},
                },
                "entity_fold": {"folded": {}},
                "usage": {
                    "calls": 2,
                    "errors": 0,
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "by_kind": {"llm": {"calls": 1}, "embed": {"calls": 1}},
                },
                "code_revisions": {
                    "deeprefine": {"commit": "engine", "dirty": False},
                    "deeprefine_skill": {"commit": "skill", "dirty": False},
                },
            },
        )
        rows = [
            {
                "result": {
                    "interaction_history": [{"answerable": index == 0}],
                    "refinement_action_raw": None if index == 0 else "action",
                }
            }
            for index in range(3)
        ]
        (case / mode / "refinement_results.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    _write_json(
        case / "summary.json",
        {
            "case_id": "redocred-case",
            "graph_sha256": "same",
            "conditions": conditions,
        },
    )


def test_aggregate_valid_paired_batch(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "batch_manifest.json",
        {"status": "complete", "case_count": 1, "seed": 2026},
    )
    _make_case(tmp_path)

    result = aggregate(tmp_path)

    assert result["status"] == "valid"
    assert result["target_denominator"] == 3
    assert result["conditions"]["open"]["endpoint_pair"] == 1
    assert result["conditions"]["closed"]["endpoint_pair"] == 1
    assert result["paired_endpoint_outcomes"] == {
        "both": 0,
        "open_only": 1,
        "closed_only": 1,
        "neither": 1,
    }
    assert result["paired_exact_two_sided_p"] == 1.0
    assert result["validation_issues"] == []


def test_aggregate_rejects_context_leak(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "batch_manifest.json",
        {"status": "complete", "case_count": 1, "seed": 2026},
    )
    _make_case(tmp_path)
    metadata_path = tmp_path / "redocred-case" / "closed" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["context"]["passed_to_original_chunk"] = True
    _write_json(metadata_path, metadata)

    result = aggregate(tmp_path)

    assert result["status"] == "invalid"
    assert any("original_chunk flag mismatch" in issue for issue in result["validation_issues"])
