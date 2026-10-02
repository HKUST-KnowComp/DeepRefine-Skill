"""Resume-safe unattended orchestrator for the 50-document Stage 3 study."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CASES = 50
MAX_CALLS_PER_CASE = 120
MAX_LLM_CALLS_PER_CASE = 40
DEFAULT_GLOBAL_CALL_CAP = 4_000
DEFAULT_GLOBAL_LLM_CAP = 1_500


class BatchGateError(RuntimeError):
    """A safe-stop condition that must not be retried automatically."""


def case_ids_from_suite(source_root: Path) -> list[str]:
    suite_path = source_root / "eval/data/prepared/redocred-mini-v1-full/suite.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    case_ids = [str(case["id"]) for case in suite["cases"]]
    if len(case_ids) != EXPECTED_CASES or len(set(case_ids)) != EXPECTED_CASES:
        raise BatchGateError(
            f"expected {EXPECTED_CASES} unique Stage 3 cases, found {len(case_ids)}"
        )
    return case_ids


def validate_completed_case(case_dir: Path) -> dict[str, Any]:
    summary_path = case_dir / "summary.json"
    if not summary_path.is_file():
        raise BatchGateError(f"incomplete case directory (no summary): {case_dir}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("case_id") != case_dir.name:
        raise BatchGateError(f"case id mismatch in {summary_path}")
    conditions = summary.get("conditions")
    if not isinstance(conditions, dict) or set(conditions) != {"open", "closed"}:
        raise BatchGateError(f"missing open/closed condition in {summary_path}")
    total_calls = 0
    total_llm = 0
    for mode in ("open", "closed"):
        condition = conditions[mode]
        usage = condition.get("usage") or {}
        calls = int(usage.get("calls", -1))
        errors = int(usage.get("errors", -1))
        llm_calls = int((usage.get("by_kind") or {}).get("llm", {}).get("calls", 0))
        metrics = condition.get("metrics") or {}
        if errors != 0:
            raise BatchGateError(f"{case_dir.name}/{mode} recorded {errors} API errors")
        if not 0 <= calls <= MAX_CALLS_PER_CASE // 2:
            raise BatchGateError(f"{case_dir.name}/{mode} invalid call count: {calls}")
        if not 0 <= llm_calls <= MAX_LLM_CALLS_PER_CASE // 2:
            raise BatchGateError(f"{case_dir.name}/{mode} invalid LLM count: {llm_calls}")
        if metrics.get("denominator") != 3:
            raise BatchGateError(f"{case_dir.name}/{mode} target denominator is not 3")
        metadata_path = case_dir / mode / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("queries_completed") != 3:
            raise BatchGateError(f"{case_dir.name}/{mode} did not complete 3 queries")
        if bool(metadata["context"]["passed_to_original_chunk"]) != (mode == "open"):
            raise BatchGateError(f"{case_dir.name}/{mode} context-mode mismatch")
        total_calls += calls
        total_llm += llm_calls
    if int(summary.get("total_calls", -1)) != total_calls:
        raise BatchGateError(f"{case_dir.name} total call count mismatch")
    return {
        "case_id": case_dir.name,
        "calls": total_calls,
        "llm_calls": total_llm,
        "open_metrics": conditions["open"]["metrics"],
        "closed_metrics": conditions["closed"]["metrics"],
    }


def scan_batch(batch_dir: Path, case_ids: list[str]) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    for case_id in case_ids:
        case_dir = batch_dir / case_id
        if case_dir.exists():
            completed.append(validate_completed_case(case_dir))
    return {
        "completed": completed,
        "calls": sum(row["calls"] for row in completed),
        "llm_calls": sum(row["llm_calls"] for row in completed),
    }


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _assert_preflight(args: argparse.Namespace) -> list[str]:
    for path, label in (
        (args.source_root, "source root"),
        (args.deeprefine_repo, "DeepRefine repository"),
        (args.env_file, "environment file"),
    ):
        if not path.exists():
            raise BatchGateError(f"missing {label}: {path}")
    if not (args.deeprefine_repo / "autorefiner/src/deeprefine.py").is_file():
        raise BatchGateError("DeepRefine repository has no autorefiner source")
    if args.global_call_cap < MAX_CALLS_PER_CASE:
        raise BatchGateError("global call cap is smaller than one safe case allowance")
    if args.global_llm_cap < MAX_LLM_CALLS_PER_CASE:
        raise BatchGateError("global LLM cap is smaller than one safe case allowance")
    return case_ids_from_suite(args.source_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--deeprefine-repo", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--global-call-cap", type=int, default=DEFAULT_GLOBAL_CALL_CAP)
    parser.add_argument("--global-llm-cap", type=int, default=DEFAULT_GLOBAL_LLM_CAP)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    args.batch_dir = args.batch_dir.resolve()
    args.deeprefine_repo = args.deeprefine_repo.resolve()
    args.env_file = args.env_file.resolve()

    case_ids = _assert_preflight(args)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "cases": len(case_ids),
                    "seed": args.seed,
                    "global_call_cap": args.global_call_cap,
                    "global_llm_cap": args.global_llm_cap,
                    "max_calls_per_case": MAX_CALLS_PER_CASE,
                    "max_llm_calls_per_case": MAX_LLM_CALLS_PER_CASE,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    args.batch_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.batch_dir / "batch_manifest.json"
    pilot_script = Path(__file__).with_name("pilot.py")
    state = scan_batch(args.batch_dir, case_ids)
    completed_ids = {row["case_id"] for row in state["completed"]}
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "seed": args.seed,
        "case_count": len(case_ids),
        "completed_case_ids": sorted(completed_ids),
        "calls": state["calls"],
        "llm_calls": state["llm_calls"],
        "global_call_cap": args.global_call_cap,
        "global_llm_cap": args.global_llm_cap,
        "updated_at_unix": time.time(),
    }
    _write_manifest(manifest_path, manifest)

    for index, case_id in enumerate(case_ids, start=1):
        if case_id in completed_ids:
            print(f"[{index}/{len(case_ids)}] skip completed {case_id}", flush=True)
            continue
        if state["calls"] + MAX_CALLS_PER_CASE > args.global_call_cap:
            raise BatchGateError("global request cap leaves no safe allowance for next case")
        if state["llm_calls"] + MAX_LLM_CALLS_PER_CASE > args.global_llm_cap:
            raise BatchGateError("global LLM cap leaves no safe allowance for next case")
        case_dir = args.batch_dir / case_id
        if case_dir.exists():
            raise BatchGateError(f"refusing to overwrite incomplete case: {case_dir}")
        log_path = args.batch_dir / f"{case_id}.log"
        command = [
            sys.executable,
            str(pilot_script),
            "--source-root",
            str(args.source_root),
            "--output-dir",
            str(case_dir),
            "--deeprefine-repo",
            str(args.deeprefine_repo),
            "--env-file",
            str(args.env_file),
            "--case-id",
            case_id,
            "--seed",
            str(args.seed),
        ]
        print(f"[{index}/{len(case_ids)}] start {case_id}", flush=True)
        with log_path.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if completed.returncode != 0:
            manifest.update(
                {
                    "status": "stopped",
                    "failed_case_id": case_id,
                    "failed_log": str(log_path),
                    "updated_at_unix": time.time(),
                }
            )
            _write_manifest(manifest_path, manifest)
            raise BatchGateError(f"case failed safely: {case_id}; inspect {log_path}")

        row = validate_completed_case(case_dir)
        state["completed"].append(row)
        state["calls"] += row["calls"]
        state["llm_calls"] += row["llm_calls"]
        completed_ids.add(case_id)
        manifest.update(
            {
                "completed_case_ids": sorted(completed_ids),
                "calls": state["calls"],
                "llm_calls": state["llm_calls"],
                "updated_at_unix": time.time(),
            }
        )
        _write_manifest(manifest_path, manifest)
        print(
            f"[{index}/{len(case_ids)}] done {case_id}: "
            f"calls={row['calls']} cumulative={state['calls']}",
            flush=True,
        )

    manifest.update({"status": "complete", "updated_at_unix": time.time()})
    _write_manifest(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchGateError as exc:
        print(f"SAFE STOP: {exc}", file=sys.stderr)
        raise SystemExit(2)
