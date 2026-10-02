"""Aggregate strict S2 transition results across repositories and executions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


RUN_NAME = re.compile(r"^(?P<repo>.+)-s(?P<seed>\d+)$")


def _count(result: dict[str, Any], slice_name: str, field: str) -> int:
    return len(result["transitions"][slice_name][field])


def aggregate(root: Path) -> list[dict[str, int]]:
    """Return pooled strict counts, grouped by execution seed."""

    per_seed: dict[int, dict[str, int]] = {}
    denominators: dict[str, tuple[int, int]] = {}
    seen: set[tuple[str, int]] = set()

    for path in sorted(root.glob("*-s*/structeval_result.json")):
        match = RUN_NAME.match(path.parent.name)
        if match is None:
            continue
        repo = match.group("repo")
        seed = int(match.group("seed"))
        if (repo, seed) in seen:
            raise ValueError(f"duplicate result for {repo} seed {seed}")
        seen.add((repo, seed))
        result = json.loads(path.read_text(encoding="utf-8"))

        dep_recovered = _count(result, "module_dependencies", "recovered_0_to_1")
        dep_missing = _count(result, "module_dependencies", "still_missing")
        sym_recovered = _count(result, "symbol_imports", "recovered_0_to_1")
        sym_missing = _count(result, "symbol_imports", "still_missing")
        current_denominators = (dep_recovered + dep_missing, sym_recovered + sym_missing)
        previous = denominators.setdefault(repo, current_denominators)
        if previous != current_denominators:
            raise ValueError(
                f"denominator drift for {repo}: {previous} vs {current_denominators}"
            )

        row = per_seed.setdefault(
            seed,
            {
                "seed": seed,
                "repositories": 0,
                "dependency_recovered": 0,
                "dependency_total": 0,
                "symbol_recovered": 0,
                "symbol_total": 0,
                "new_unverified": 0,
            },
        )
        row["repositories"] += 1
        row["dependency_recovered"] += dep_recovered
        row["dependency_total"] += current_denominators[0]
        row["symbol_recovered"] += sym_recovered
        row["symbol_total"] += current_denominators[1]
        row["new_unverified"] += _count(
            result, "unverified_import_edges", "new_unverified"
        )

    if not per_seed:
        raise ValueError(f"no strict result files found under {root}")
    expected_repositories = len(denominators)
    for seed, row in per_seed.items():
        if row["repositories"] != expected_repositories:
            raise ValueError(
                f"seed {seed} has {row['repositories']} repositories; "
                f"expected {expected_repositories}"
            )
    return [per_seed[seed] for seed in sorted(per_seed)]


def render_markdown(rows: list[dict[str, int]]) -> str:
    lines = [
        "| Execution | Repositories | Dependency strict | Symbol strict | New unverified |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        dep_rate = 100 * row["dependency_recovered"] / row["dependency_total"]
        sym_rate = 100 * row["symbol_recovered"] / row["symbol_total"]
        lines.append(
            f"| {row['seed']} | {row['repositories']} | "
            f"{row['dependency_recovered']}/{row['dependency_total']} "
            f"({dep_rate:.1f}%) | {row['symbol_recovered']}/{row['symbol_total']} "
            f"({sym_rate:.1f}%) | {row['new_unverified']} |"
        )
    return "\n".join(lines) + "\n"


def render_json(rows: list[dict[str, int]]) -> str:
    payload = {
        "schema_version": 1,
        "study": "s2-code-multirepo",
        "status": "audited_offline_rescore",
        "metric": {
            "primary": "pooled strict module-dependency recovery",
            "secondary": "strict target-module symbol-import recovery",
            "counter_metric": "new unverified import claims",
        },
        "executions": rows,
        "interpretation": (
            "Candidate graphs are historical generation artifacts rescored with the "
            "corrected strict matcher; this is not a new model rerun."
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    rows = aggregate(args.input_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(rows), encoding="utf-8")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(render_json(rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
