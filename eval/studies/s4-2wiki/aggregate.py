"""Offline answer/usage aggregation for corrected Stage 4 outputs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.benchmarking.metrics import answer_exact_match, answer_token_f1


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _usage(path: Path) -> dict[str, int]:
    usage = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    if not path.is_file():
        return usage
    for line in path.read_text(encoding="utf-8").splitlines():
        detail = json.loads(line)
        if detail.get("record_type") != "detail":
            continue
        usage["calls"] += 1
        usage["errors"] += int(bool(detail.get("error")))
        usage["prompt_tokens"] += int(detail.get("prompt_tokens") or 0)
        usage["completion_tokens"] += int(detail.get("completion_tokens") or 0)
    return usage


def _add_usage(total: dict[str, int], current: dict[str, int]) -> None:
    for key in total:
        total[key] += current[key]


def aggregate(suite_path: Path, batch_dir: Path, expected: int) -> dict[str, Any]:
    suite = _read_json(suite_path)
    by_id = {case["id"]: case for case in suite["cases"]}
    manifest = _read_json(batch_dir / "batch-manifest.json")
    rows: list[dict[str, Any]] = []
    usage = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    protocol = {
        "cases": 0,
        "zero_action_cases": 0,
        "with_action_cases": 0,
        "changed_graph_cases": 0,
        "same_graph_cases": 0,
        "action_count": 0,
        "reader_config_count": 0,
        "failed_attempt_calls": 0,
        "failed_attempt_errors": 0,
        "manifest_calls": int(manifest.get("calls", 0)),
    }
    reader_configs: set[str] = set()
    reader_config_value: dict[str, Any] | None = None
    seen_ids: set[str] = set()
    for path in sorted((batch_dir / "cases").glob("*/protocol-result.json")):
        result = _read_json(path)
        case_dir = path.parent
        case_id = result["case_id"]
        if case_id in seen_ids:
            raise ValueError(f"duplicate Stage 4 result for {case_id}")
        seen_ids.add(case_id)
        if case_id not in by_id:
            raise ValueError(f"unknown Stage 4 case {case_id}")
        phases = {
            name: _read_json(case_dir / name / "phase-result.json")
            for name in ("baseline-reader", "refinement", "post-reader")
        }
        pre, refinement, post = (
            phases["baseline-reader"],
            phases["refinement"],
            phases["post-reader"],
        )
        if pre.get("reader_config") != post.get("reader_config"):
            raise ValueError(f"{case_id}: pre/post reader configuration mismatch")
        reader_configs.add(json.dumps(pre.get("reader_config"), sort_keys=True))
        if reader_config_value is None:
            reader_config_value = pre.get("reader_config")
        if len({pre.get("process_id"), refinement.get("process_id"), post.get("process_id")}) != 3:
            raise ValueError(f"{case_id}: phases did not use three processes")
        if len({pre.get("instance_id"), refinement.get("instance_id"), post.get("instance_id")}) != 3:
            raise ValueError(f"{case_id}: phases did not use three instances")
        if not pre.get("index_rebuilt") or not post.get("index_rebuilt"):
            raise ValueError(f"{case_id}: reader index was not rebuilt")
        if pre.get("graph_hash_before") != pre.get("graph_hash_after"):
            raise ValueError(f"{case_id}: baseline reader modified its graph")
        if post.get("graph_hash_before") != post.get("graph_hash_after"):
            raise ValueError(f"{case_id}: post reader modified its graph")
        if pre.get("graph_hash_before") != result.get("baseline_graph_hash"):
            raise ValueError(f"{case_id}: baseline graph hash mismatch")
        if post.get("graph_hash_before") != result.get("candidate_graph_hash"):
            raise ValueError(f"{case_id}: post reader did not load the candidate graph")
        action_count = int(result.get("action_count", 0))
        if action_count != int(refinement.get("action_count", -1)):
            raise ValueError(f"{case_id}: action count mismatch")
        same_graph = result.get("baseline_graph_hash") == result.get("candidate_graph_hash")
        if action_count == 0 and not same_graph:
            raise ValueError(f"{case_id}: zero-action case changed graph")
        if action_count > 0 and same_graph:
            raise ValueError(f"{case_id}: applied actions produced no graph change")
        if action_count == 0:
            if pre.get("reader_context_hash") != post.get("reader_context_hash"):
                raise ValueError(f"{case_id}: zero-action reader contexts differ")
            if result.get("pre_answer") != result.get("post_answer"):
                raise ValueError(f"{case_id}: zero-action reader answers differ")

        protocol["cases"] += 1
        protocol["action_count"] += action_count
        protocol["zero_action_cases" if action_count == 0 else "with_action_cases"] += 1
        protocol["same_graph_cases" if same_graph else "changed_graph_cases"] += 1

        case = by_id[case_id]
        gold = case.get("answers") or []
        pre_em = answer_exact_match(result["pre_answer"], gold)
        post_em = answer_exact_match(result["post_answer"], gold)
        pre_f1 = answer_token_f1(result["pre_answer"], gold)
        post_f1 = answer_token_f1(result["post_answer"], gold)
        rows.append(
            {
                **result,
                "question_type": case["question_type"],
                "gold_answers": gold,
                "pre_em": pre_em,
                "post_em": post_em,
                "delta_em": post_em - pre_em,
                "pre_f1": pre_f1,
                "post_f1": post_f1,
                "delta_f1": post_f1 - pre_f1,
            }
        )
        for usage_path in case_dir.glob("*/api-usage.jsonl"):
            _add_usage(usage, _usage(usage_path))
    if len(rows) != expected:
        raise ValueError(f"expected {expected} completed cases, found {len(rows)}")
    if manifest.get("status") != "complete":
        raise ValueError(f"batch manifest status is {manifest.get('status')!r}")
    completed = set(manifest.get("completed_case_ids", []))
    if completed != seen_ids:
        raise ValueError("batch manifest completed IDs do not match result cases")

    failed_usage = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for usage_path in (batch_dir / "failed-attempts").glob("**/api-usage.jsonl"):
        _add_usage(failed_usage, _usage(usage_path))
    protocol["failed_attempt_calls"] = failed_usage["calls"]
    protocol["failed_attempt_errors"] = failed_usage["errors"]
    if usage["calls"] + failed_usage["calls"] != protocol["manifest_calls"]:
        raise ValueError("successful and archived usage does not match manifest calls")
    protocol["reader_config_count"] = len(reader_configs)
    if len(reader_configs) != 1:
        raise ValueError(f"expected one fixed reader config, found {len(reader_configs)}")

    def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {
                "n": 0,
                "em_before": None,
                "em_after": None,
                "em_delta": None,
                "f1_before": None,
                "f1_after": None,
                "f1_delta": None,
                "em_improved": 0,
                "em_regressed": 0,
                "em_unchanged": 0,
                "f1_improved": 0,
                "f1_regressed": 0,
                "f1_unchanged": 0,
            }
        return {
            "n": len(items),
            "em_before": fmean(row["pre_em"] for row in items),
            "em_after": fmean(row["post_em"] for row in items),
            "em_delta": fmean(row["delta_em"] for row in items),
            "f1_before": fmean(row["pre_f1"] for row in items),
            "f1_after": fmean(row["post_f1"] for row in items),
            "f1_delta": fmean(row["delta_f1"] for row in items),
            "em_improved": sum(row["delta_em"] > 0 for row in items),
            "em_regressed": sum(row["delta_em"] < 0 for row in items),
            "em_unchanged": sum(row["delta_em"] == 0 for row in items),
            "f1_improved": sum(row["delta_f1"] > 0 for row in items),
            "f1_regressed": sum(row["delta_f1"] < 0 for row in items),
            "f1_unchanged": sum(row["delta_f1"] == 0 for row in items),
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["question_type"]].append(row)
    report = {
        "schema_version": 1,
        "suite_id": suite["suite_id"],
        "overall": metrics(rows),
        "by_question_type": {key: metrics(value) for key, value in sorted(grouped.items())},
        "zero_action": metrics([row for row in rows if row["action_count"] == 0]),
        "with_action": metrics([row for row in rows if row["action_count"] > 0]),
        "usage_detail_rows_only": usage,
        "protocol_validation": protocol,
        "reader_config": reader_config_value,
        "cases": rows,
    }
    return report


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "cases"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compact-output", type=Path)
    parser.add_argument("--expected", type=int, required=True)
    args = parser.parse_args()
    report = aggregate(args.suite, args.batch_dir, args.expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.compact_output is not None:
        args.compact_output.parent.mkdir(parents=True, exist_ok=True)
        args.compact_output.write_text(
            json.dumps(compact_report(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
