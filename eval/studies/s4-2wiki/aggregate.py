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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=int, required=True)
    args = parser.parse_args()

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in suite["cases"]}
    rows = []
    usage = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for path in sorted((args.batch_dir / "cases").glob("*/protocol-result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        case = by_id[result["case_id"]]
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
        for usage_path in path.parent.glob("*/api-usage.jsonl"):
            for line in usage_path.read_text(encoding="utf-8").splitlines():
                detail = json.loads(line)
                if detail.get("record_type") != "detail":
                    continue
                usage["calls"] += 1
                usage["errors"] += int(bool(detail.get("error")))
                usage["prompt_tokens"] += int(detail.get("prompt_tokens") or 0)
                usage["completion_tokens"] += int(detail.get("completion_tokens") or 0)
    if len(rows) != args.expected:
        raise SystemExit(f"expected {args.expected} completed cases, found {len(rows)}")

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
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
