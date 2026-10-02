"""Resume-safe unattended runner for corrected Stage 4 pilot/full batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class BatchGateError(RuntimeError):
    pass


MAX_CALLS_PER_CASE = 40


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _env_names(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive_failed_attempt(
    *, output_dir: Path, case_dir: Path, log_path: Path, case_id: str
) -> tuple[Path, dict[str, int]]:
    failed_usage = _usage(case_dir) if case_dir.exists() else {
        "calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0
    }
    archive_root = output_dir / "failed-attempts"
    archive_root.mkdir(exist_ok=True)
    attempt = 1
    archived_case = archive_root / f"{case_id}-attempt{attempt}"
    while archived_case.exists():
        attempt += 1
        archived_case = archive_root / f"{case_id}-attempt{attempt}"
    if case_dir.exists():
        shutil.move(str(case_dir), str(archived_case))
    if log_path.exists():
        shutil.move(str(log_path), str(archived_case.with_suffix(".log")))
    return archived_case, failed_usage


def _select_cases(suite: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    cases = list(suite["cases"])
    if mode == "full":
        if len(cases) != 64:
            raise BatchGateError(f"full mode requires 64 cases, found {len(cases)}")
        return cases
    selected: dict[str, dict[str, Any]] = {}
    for case in cases:
        selected.setdefault(str(case["question_type"]), case)
    if len(selected) != 4:
        raise BatchGateError("pilot mode requires exactly four question types")
    return [selected[key] for key in sorted(selected)]


def _validate_inputs(
    suite: dict[str, Any], baseline_root: Path
) -> dict[str, str]:
    source_sha = str((suite.get("source") or {}).get("sha256") or "")
    counts: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for case in suite.get("cases", []):
        case_id = str(case["id"])
        question_type = str(case["question_type"])
        counts[question_type] = counts.get(question_type, 0) + 1
        path = baseline_root / case_id / "baseline-graph.json"
        if not path.is_file():
            raise BatchGateError(f"missing baseline: {path}")
        graph = json.loads(path.read_text(encoding="utf-8"))
        metadata = graph.get("graph") or {}
        if metadata.get("suite") != suite["suite_id"]:
            raise BatchGateError(f"{case_id}: baseline suite mismatch")
        if source_sha and metadata.get("source_sha256") != source_sha:
            raise BatchGateError(f"{case_id}: baseline source SHA mismatch")
        if metadata.get("question_type") != question_type:
            raise BatchGateError(f"{case_id}: baseline question type mismatch")
        hashes[case_id] = _sha256(path)
    if len(suite.get("cases", [])) != 64 or sorted(counts.values()) != [16] * 4:
        raise BatchGateError(f"unbalanced 2Wiki suite: {counts}")
    if len(set(hashes.values())) != len(hashes):
        raise BatchGateError("duplicate baseline graph hashes")
    return hashes


def _usage(case_dir: Path) -> dict[str, int]:
    totals = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for path in case_dir.glob("*/api-usage.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") != "detail":
                continue
            totals["calls"] += 1
            totals["errors"] += int(bool(row.get("error")))
            totals["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
            totals["completion_tokens"] += int(row.get("completion_tokens") or 0)
    return totals


def _validate_completed(case_dir: Path, case_id: str) -> dict[str, Any]:
    result_path = case_dir / "protocol-result.json"
    if not result_path.is_file():
        raise BatchGateError(f"incomplete case directory: {case_dir}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("case_id") != case_id:
        raise BatchGateError(f"case id mismatch: {result_path}")
    usage = _usage(case_dir)
    if usage["errors"]:
        raise BatchGateError(f"{case_id}: recorded API errors")
    if usage["calls"] > MAX_CALLS_PER_CASE:
        raise BatchGateError(
            f"{case_id}: {usage['calls']} calls exceeds per-case cap {MAX_CALLS_PER_CASE}"
        )
    return {"case_id": case_id, "usage": usage}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--deeprefine-repo", type=Path, required=True)
    parser.add_argument("--global-call-cap", type=int, required=True)
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="archive an incomplete failed case directory before retrying it",
    )
    parser.add_argument(
        "--max-case-attempts",
        type=int,
        default=3,
        help="automatically archive and retry a failed case (default: 3 attempts)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_case_attempts < 1:
        raise BatchGateError("--max-case-attempts must be at least 1")

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    if suite.get("suite_id") != "2wiki-mini-v1":
        raise BatchGateError("wrong suite id")
    baseline_hashes = _validate_inputs(suite, args.baseline_root)
    cases = _select_cases(suite, args.mode)
    env = _env_names(args.env_file)
    model = env.get("DEEPREFINE_MODEL", "")
    embedding_model = env.get("DEEPREFINE_EMBED_MODEL", "")
    if not model or not embedding_model:
        raise BatchGateError("model names are missing from env file")
    for path in (args.baseline_root, args.deeprefine_repo, args.env_file):
        if not path.exists():
            raise BatchGateError(f"missing required path: {path}")

    plan = {
        "schema_version": 1,
        "mode": args.mode,
        "suite_id": suite["suite_id"],
        "case_ids": [case["id"] for case in cases],
        "case_count": len(cases),
        "global_call_cap": args.global_call_cap,
        "max_calls_per_case": MAX_CALLS_PER_CASE,
        "model": model,
        "embedding_model": embedding_model,
        "baseline_hash_count": len(baseline_hashes),
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = args.output_dir / "cases"
    cases_dir.mkdir(exist_ok=True)
    manifest_path = args.output_dir / "batch-manifest.json"
    worker = Path(__file__).with_name("worker.py")
    completed: list[str] = []
    cumulative_calls = 0
    manifest = {
        **plan,
        "baseline_hashes": baseline_hashes,
        "status": "running",
        "completed_case_ids": completed,
    }
    _write_json(manifest_path, manifest)

    for index, case in enumerate(cases, 1):
        case_id = str(case["id"])
        case_dir = cases_dir / case_id
        if case_dir.exists():
            if (case_dir / "protocol-result.json").is_file():
                row = _validate_completed(case_dir, case_id)
                completed.append(case_id)
                cumulative_calls += row["usage"]["calls"]
                print(f"[{index}/{len(cases)}] verified completed {case_id}", flush=True)
                continue
            if not args.retry_incomplete:
                raise BatchGateError(
                    f"incomplete case directory: {case_dir}; "
                    "rerun with --retry-incomplete to archive and retry"
                )
            old_log = args.output_dir / f"{case_id}.log"
            archived_case, failed_usage = _archive_failed_attempt(
                output_dir=args.output_dir,
                case_dir=case_dir,
                log_path=old_log,
                case_id=case_id,
            )
            cumulative_calls += failed_usage["calls"]
            print(
                f"[{index}/{len(cases)}] archived incomplete case -> {archived_case} "
                f"(failed-attempt calls retained={failed_usage['calls']})",
                flush=True,
            )
        if cumulative_calls + MAX_CALLS_PER_CASE > args.global_call_cap:
            raise BatchGateError("global call cap leaves no safe allowance for next case")
        baseline = args.baseline_root / case_id / "baseline-graph.json"
        if not baseline.is_file():
            raise BatchGateError(f"missing baseline: {baseline}")
        log_path = args.output_dir / f"{case_id}.log"
        command = [
            sys.executable,
            str(worker),
            "case",
            "--case-id", case_id,
            "--question", str(case["question"]),
            "--baseline-graph", str(baseline),
            "--case-root", str(case_dir),
            "--env-file", str(args.env_file),
            "--deeprefine-repo", str(args.deeprefine_repo),
            "--model", model,
            "--embedding-model", embedding_model,
        ]
        for attempt in range(1, args.max_case_attempts + 1):
            print(
                f"[{index}/{len(cases)}] start {case_id} "
                f"(attempt {attempt}/{args.max_case_attempts})",
                flush=True,
            )
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if not process.returncode:
                break
            archived_case, failed_usage = _archive_failed_attempt(
                output_dir=args.output_dir,
                case_dir=case_dir,
                log_path=log_path,
                case_id=case_id,
            )
            cumulative_calls += failed_usage["calls"]
            print(
                f"[{index}/{len(cases)}] attempt failed; archived -> {archived_case} "
                f"(calls retained={failed_usage['calls']})",
                flush=True,
            )
            if cumulative_calls + MAX_CALLS_PER_CASE > args.global_call_cap:
                raise BatchGateError("global call cap leaves no safe retry allowance")
        else:
            manifest.update(
                status="stopped",
                failed_case_id=case_id,
                failed_log=str(log_path),
                updated_at_unix=time.time(),
            )
            _write_json(manifest_path, manifest)
            raise BatchGateError(
                f"case failed safely after {args.max_case_attempts} attempts: {case_id}"
            )
        row = _validate_completed(case_dir, case_id)
        completed.append(case_id)
        cumulative_calls += row["usage"]["calls"]
        if cumulative_calls > args.global_call_cap:
            raise BatchGateError("global call cap exceeded")
        manifest.update(
            completed_case_ids=completed,
            calls=cumulative_calls,
            updated_at_unix=time.time(),
        )
        _write_json(manifest_path, manifest)
        print(f"[{index}/{len(cases)}] done {case_id}", flush=True)

    manifest.update(status="complete", calls=cumulative_calls, updated_at_unix=time.time())
    _write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchGateError as exc:
        print(f"SAFE STOP: {exc}", file=sys.stderr)
        raise SystemExit(2)
