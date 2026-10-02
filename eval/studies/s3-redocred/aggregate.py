#!/usr/bin/env python3
"""Aggregate and validate a completed Stage 3 open/closed batch."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


MODES = ("open", "closed")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _exact_sign_test(open_only: int, closed_only: int) -> float | None:
    """Two-sided exact binomial test for paired discordant outcomes."""
    n = open_only + closed_only
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(open_only, closed_only) + 1))
    return min(1.0, 2.0 * tail / (2**n))


def aggregate(batch_dir: Path) -> dict[str, Any]:
    manifest = _read_json(batch_dir / "batch_manifest.json")
    case_dirs = sorted(
        path
        for path in batch_dir.iterdir()
        if path.is_dir() and path.name.startswith("redocred-")
    )
    issues: list[str] = []
    expected = int(manifest.get("case_count", 0))
    if manifest.get("status") != "complete":
        issues.append(f"batch status is {manifest.get('status')!r}, not 'complete'")
    if len(case_dirs) != expected:
        issues.append(f"found {len(case_dirs)} case directories, expected {expected}")

    per_mode = {
        mode: Counter(
            cases=0,
            queries=0,
            strict_relation_label=0,
            endpoint_pair=0,
            action_queries=0,
            first_step_yes=0,
            folded_entities=0,
            truncated_contexts=0,
            calls=0,
            llm_calls=0,
            embed_calls=0,
            errors=0,
            prompt_tokens=0,
            completion_tokens=0,
        )
        for mode in MODES
    }
    paired = Counter(both=0, open_only=0, closed_only=0, neither=0)
    revisions: dict[str, set[tuple[str, bool]]] = {
        "deeprefine": set(),
        "deeprefine_skill": set(),
    }

    for case_dir in case_dirs:
        summary = _read_json(case_dir / "summary.json")
        if summary.get("case_id") != case_dir.name:
            issues.append(f"{case_dir.name}: summary case_id mismatch")
        targets_by_mode: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = {}
        metadata_by_mode: dict[str, dict[str, Any]] = {}

        for mode in MODES:
            condition = summary.get("conditions", {}).get(mode, {})
            metrics = condition.get("metrics", {})
            metadata = _read_json(case_dir / mode / "metadata.json")
            rows = _read_jsonl(case_dir / mode / "refinement_results.jsonl")
            metadata_by_mode[mode] = metadata
            target_rows = metrics.get("targets", [])
            targets_by_mode[mode] = {
                (row["source"], row["relation"], row["target"]): row
                for row in target_rows
            }

            stats = per_mode[mode]
            stats["cases"] += 1
            stats["queries"] += len(rows)
            stats["strict_relation_label"] += int(metrics.get("strict_relation_label", 0))
            stats["endpoint_pair"] += int(metrics.get("endpoint_pair_added", 0))
            stats["action_queries"] += sum(
                bool((row.get("result") or {}).get("refinement_action_raw"))
                for row in rows
            )
            stats["first_step_yes"] += sum(
                bool(history := (row.get("result") or {}).get("interaction_history"))
                and len(history) == 1
                and history[0].get("answerable") is True
                for row in rows
            )
            stats["folded_entities"] += len(metadata.get("entity_fold", {}).get("folded", {}))
            stats["truncated_contexts"] += int(
                bool(metadata.get("context", {}).get("truncation", {}).get("truncated"))
            )
            usage = metadata.get("usage", {})
            stats["calls"] += int(usage.get("calls", 0))
            stats["errors"] += int(usage.get("errors", 0))
            stats["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
            stats["completion_tokens"] += int(usage.get("completion_tokens", 0))
            stats["llm_calls"] += int(usage.get("by_kind", {}).get("llm", {}).get("calls", 0))
            stats["embed_calls"] += int(usage.get("by_kind", {}).get("embed", {}).get("calls", 0))

            if len(rows) != 3 or int(metrics.get("denominator", -1)) != 3:
                issues.append(f"{case_dir.name}/{mode}: expected exactly three targets")
            context = metadata.get("context", {})
            should_have_context = mode == "open"
            if bool(context.get("passed_to_original_chunk")) != should_have_context:
                issues.append(f"{case_dir.name}/{mode}: original_chunk flag mismatch")
            if (int(context.get("original_chunk_chars", 0)) > 0) != should_have_context:
                issues.append(f"{case_dir.name}/{mode}: original_chunk length mismatch")
            if metadata.get("graph_sha256") != summary.get("graph_sha256"):
                issues.append(f"{case_dir.name}/{mode}: graph hash mismatch")
            for repo_name, revision in metadata.get("code_revisions", {}).items():
                if repo_name in revisions:
                    revisions[repo_name].add(
                        (str(revision.get("commit", "")), bool(revision.get("dirty")))
                    )

        open_meta, closed_meta = metadata_by_mode["open"], metadata_by_mode["closed"]
        if open_meta.get("graph_sha256") != closed_meta.get("graph_sha256"):
            issues.append(f"{case_dir.name}: open/closed graph hashes differ")
        if (
            open_meta.get("context", {}).get("selected_sha256")
            != closed_meta.get("context", {}).get("selected_sha256")
        ):
            issues.append(f"{case_dir.name}: open/closed source hashes differ")

        open_targets = targets_by_mode["open"]
        closed_targets = targets_by_mode["closed"]
        if set(open_targets) != set(closed_targets):
            issues.append(f"{case_dir.name}: open/closed target sets differ")
            continue
        for key in open_targets:
            open_hit = bool(open_targets[key].get("endpoint_pair_added"))
            closed_hit = bool(closed_targets[key].get("endpoint_pair_added"))
            if open_hit and closed_hit:
                paired["both"] += 1
            elif open_hit:
                paired["open_only"] += 1
            elif closed_hit:
                paired["closed_only"] += 1
            else:
                paired["neither"] += 1

    denominator = sum(paired.values())
    revision_output = {
        name: [
            {"commit": commit, "dirty": dirty}
            for commit, dirty in sorted(values)
        ]
        for name, values in revisions.items()
    }
    result = {
        "schema_version": 1,
        "study": "s3-redocred",
        "dataset": "Re-DocRED",
        "seed": manifest.get("seed"),
        "status": "valid" if not issues else "invalid",
        "case_count": len(case_dirs),
        "target_denominator": denominator,
        "conditions": {
            mode: dict(sorted(per_mode[mode].items())) for mode in MODES
        },
        "paired_endpoint_outcomes": dict(paired),
        "paired_exact_two_sided_p": _exact_sign_test(
            paired["open_only"], paired["closed_only"]
        ),
        "code_revisions": revision_output,
        "validation_issues": issues,
        "interpretation": {
            "primary": "strict relation-label recovery",
            "secondary": "relation-agnostic endpoint-pair coverage",
            "boundary": (
                "Single-seed endpoint coverage does not establish an open-book effect; "
                "free-form relation labels are not strict semantic recovery."
            ),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = aggregate(args.batch_dir)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
