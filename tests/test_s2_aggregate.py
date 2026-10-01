from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "studies"
    / "s2-code-multirepo"
    / "aggregate.py"
)
SPEC = importlib.util.spec_from_file_location("s2_aggregate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
s2_aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s2_aggregate)


def _write_result(
    root: Path,
    repo: str,
    seed: int,
    *,
    dep_recovered: int,
    dep_missing: int,
    sym_recovered: int,
    sym_missing: int,
    new_unverified: int,
) -> None:
    destination = root / f"{repo}-s{seed}" / "structeval_result.json"
    destination.parent.mkdir(parents=True)
    payload = {
        "transitions": {
            "module_dependencies": {
                "recovered_0_to_1": ["d"] * dep_recovered,
                "still_missing": ["d"] * dep_missing,
            },
            "symbol_imports": {
                "recovered_0_to_1": ["s"] * sym_recovered,
                "still_missing": ["s"] * sym_missing,
            },
            "unverified_import_edges": {
                "new_unverified": ["u"] * new_unverified,
                "persistent": [],
                "resolved": [],
            },
        }
    }
    destination.write_text(json.dumps(payload), encoding="utf-8")


def test_aggregate_pools_counts_by_seed(tmp_path: Path) -> None:
    for seed in (2026, 2027):
        _write_result(
            tmp_path,
            "alpha",
            seed,
            dep_recovered=1,
            dep_missing=2,
            sym_recovered=0,
            sym_missing=4,
            new_unverified=seed - 2025,
        )
        _write_result(
            tmp_path,
            "beta",
            seed,
            dep_recovered=2,
            dep_missing=0,
            sym_recovered=0,
            sym_missing=3,
            new_unverified=1,
        )

    rows = s2_aggregate.aggregate(tmp_path)

    assert rows[0] == {
        "seed": 2026,
        "repositories": 2,
        "dependency_recovered": 3,
        "dependency_total": 5,
        "symbol_recovered": 0,
        "symbol_total": 7,
        "new_unverified": 2,
    }
    assert "3/5 (60.0%)" in s2_aggregate.render_markdown(rows)


def test_aggregate_rejects_denominator_drift(tmp_path: Path) -> None:
    _write_result(
        tmp_path,
        "alpha",
        2026,
        dep_recovered=1,
        dep_missing=2,
        sym_recovered=0,
        sym_missing=4,
        new_unverified=0,
    )
    _write_result(
        tmp_path,
        "alpha",
        2027,
        dep_recovered=1,
        dep_missing=3,
        sym_recovered=0,
        sym_missing=4,
        new_unverified=0,
    )

    with pytest.raises(ValueError, match="denominator drift"):
        s2_aggregate.aggregate(tmp_path)
