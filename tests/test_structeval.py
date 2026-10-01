"""Public-contract tests for the structural evaluator (AST gold vs graph).

The gold side is extracted with stdlib ``ast`` from tiny fixture trees, so
every expected number below is hand-checkable — the same discipline the
bundled smoke suite follows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Import the engine through the ``eval.benchmarking`` namespace package.
# The repo root goes on sys.path so the import resolves; ``eval/`` is
# intentionally left without an ``__init__.py`` so it never enters the wheel.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from eval.benchmarking import cli as benchmark_cli
from eval.benchmarking.ast_gold import ROUTE_A_EXCLUDED_TOP_DIRS, extract_gold
from eval.benchmarking.cli import main as bench_main
from eval.benchmarking.structeval import (
    compare_runs,
    emit_queries,
    evaluate_structure,
)


def _write_tree(root: Path) -> None:
    """Six-module fixture tree with module-level AND function-scoped imports."""

    pkg = root / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("from pkg import alpha\n", encoding="utf-8")
    (pkg / "alpha.py").write_text(
        "import pkg.sub.charlie\n"
        "from pkg.beta import helper\n"
        "\n"
        "def runner():\n"
        "    from pkg import delta\n"
        "    return delta\n",
        encoding="utf-8",
    )
    (pkg / "beta.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "delta.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "charlie.py").write_text("", encoding="utf-8")


def test_extract_gold_enumerates_modules_symbols_and_imports(tmp_path: Path) -> None:
    tree = tmp_path / "src"
    _write_tree(tree)

    gold = extract_gold(tree, source_tag="test")

    assert gold.modules == (
        "pkg/__init__.py",
        "pkg/alpha.py",
        "pkg/beta.py",
        "pkg/delta.py",
        "pkg/sub/__init__.py",
        "pkg/sub/charlie.py",
    )
    assert gold.file_count == 6
    # Module dependencies include the function-scoped ``from pkg import delta``.
    assert gold.module_dependencies() == {
        ("pkg/__init__.py", "pkg/alpha.py"),
        ("pkg/alpha.py", "pkg/beta.py"),
        ("pkg/alpha.py", "pkg/sub/charlie.py"),
        ("pkg/alpha.py", "pkg/delta.py"),
    }
    assert gold.symbol_imports() == {("pkg/alpha.py", "pkg/beta.py", "helper")}
    assert gold.symbols["pkg/beta.py"] == ("helper",)


def test_extract_gold_resolves_relative_and_skips_external(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg2"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "one.py").write_text(
        "import os\n"
        "from .two import thing\n"
        "from . import three\n"
        "from ..missing import gone\n",
        encoding="utf-8",
    )
    (pkg / "two.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    (pkg / "three.py").write_text("", encoding="utf-8")

    gold = extract_gold(tmp_path)

    # ``import os`` (stdlib) and ``from ..missing import gone`` (outside the
    # tree) are excluded; both relative forms resolve to project modules.
    assert gold.module_dependencies() == {
        ("pkg2/one.py", "pkg2/two.py"),
        ("pkg2/one.py", "pkg2/three.py"),
    }
    assert gold.symbol_imports() == {("pkg2/one.py", "pkg2/two.py", "thing")}


def test_extract_gold_src_layout_strips_container_and_resolves_absolute(
    tmp_path: Path,
) -> None:
    """src/ container prefix is stripped so absolute in-package imports hit."""

    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(
        "import pkg.engine\nfrom pkg import cache\n", encoding="utf-8"
    )
    (pkg / "engine.py").write_text("", encoding="utf-8")
    (pkg / "cache.py").write_text("", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_api.py").write_text(
        "from pkg.api import run\n", encoding="utf-8"
    )

    gold = extract_gold(tmp_path)

    # Default keeps every tree (v0.2.0 behaviour); module paths stay
    # tree-relative while names resolve container-free.
    assert gold.modules == (
        "src/pkg/__init__.py",
        "src/pkg/api.py",
        "src/pkg/cache.py",
        "src/pkg/engine.py",
        "tests/test_api.py",
    )
    assert gold.module_dependencies() == {
        ("src/pkg/api.py", "src/pkg/engine.py"),
        ("src/pkg/api.py", "src/pkg/cache.py"),
        ("tests/test_api.py", "src/pkg/api.py"),
    }

    scoped = extract_gold(tmp_path, excluded_top_dirs=("tests",))
    assert scoped.modules == (
        "src/pkg/__init__.py",
        "src/pkg/api.py",
        "src/pkg/cache.py",
        "src/pkg/engine.py",
    )
    assert scoped.module_dependencies() == {
        ("src/pkg/api.py", "src/pkg/engine.py"),
        ("src/pkg/api.py", "src/pkg/cache.py"),
    }


def test_extract_gold_lib_layout_resolves_relative_under_container(
    tmp_path: Path,
) -> None:
    """lib/ container: relative imports resolve against the stripped base."""

    pkg = tmp_path / "lib" / "yaml"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "loader.py").write_text(
        "from .error import YAMLError\n", encoding="utf-8"
    )
    (pkg / "error.py").write_text("class YAMLError:\n    pass\n", encoding="utf-8")
    sibling = tmp_path / "lib" / "_ext"
    sibling.mkdir()
    (sibling / "__init__.py").write_text("", encoding="utf-8")

    gold = extract_gold(tmp_path)

    assert gold.module_dependencies() == {("lib/yaml/loader.py", "lib/yaml/error.py")}
    assert gold.symbol_imports() == {("lib/yaml/loader.py", "lib/yaml/error.py", "YAMLError")}


def test_extract_gold_with_statements_do_not_crash(tmp_path: Path) -> None:
    """Top-level and nested ``with`` blocks bind names instead of raising."""

    mod = tmp_path / "mod.py"
    mod.write_text(
        "with open('a') as fh:\n"
        "    data = fh.read()\n"
        "\n"
        "if flag:\n"
        "    with open('b') as g:\n"
        "        more = g.read()\n"
        "\n"
        "async with ctx():\n"
        "    pass\n",
        encoding="utf-8",
    )

    gold = extract_gold(tmp_path)

    assert gold.file_count == 1
    assert "data" in gold.symbols["mod.py"]
    assert "more" in gold.symbols["mod.py"]


def test_route_a_scope_rule_is_frozen() -> None:
    """The pre-registered exclusion rule must not drift silently."""

    assert ROUTE_A_EXCLUDED_TOP_DIRS == (
        "tests", "test", "docs", "doc", "examples", "example",
        "benchmarks", "benchmark", "tools", "scripts",
        "requirements", "ci_tools", "packaging",
    )


def _graph_fixture() -> dict:
    """A hand-checkable Graphify node-link graph for the pkg fixture tree.

    Encodes three error classes at once: one missing gold dependency
    (alpha -> delta), one unverified claim (alpha -> ghost), and one
    phantom module node — plus one missing module node.
    """

    return {
        "directed": True,
        "multigraph": True,
        "nodes": [
            {"id": "init", "label": "__init__.py", "source_file": "pkg/__init__.py"},
            {"id": "alpha", "label": "alpha.py", "source_file": "pkg/alpha.py"},
            {"id": "beta", "label": "beta.py", "source_file": "pkg/beta.py"},
            {"id": "charlie", "label": "charlie.py", "source_file": "pkg/sub/charlie.py"},
            {"id": "delta", "label": "delta.py", "source_file": "pkg/delta.py"},
            {"id": "ghost", "label": "ghost.py", "source_file": "pkg/ghost.py"},
            {"id": "helper", "label": "helper()", "source_file": "pkg/beta.py"},
        ],
        "links": [
            {"source": "init", "target": "alpha", "relation": "imports"},
            {"source": "alpha", "target": "charlie", "relation": "imports"},
            {"source": "alpha", "target": "beta", "relation": "imports"},
            {"source": "alpha", "target": "helper", "relation": "imports_from"},
            {"source": "alpha", "target": "ghost", "relation": "imports"},
        ],
    }


def test_evaluate_structure_is_hand_checkable(tmp_path: Path) -> None:
    tree = tmp_path / "src"
    _write_tree(tree)
    gold = extract_gold(tree)

    result = evaluate_structure(gold, _graph_fixture())

    # Module nodes: 13-style counting — 6 predicted, 5 real (ghost is
    # phantom), 6 gold modules with sub/__init__ unrepresented.
    assert result["metrics"]["module_nodes"] == {
        "precision": pytest.approx(5 / 6),
        "recall": pytest.approx(5 / 6),
        "f1": pytest.approx(5 / 6),
        "tp": 5,
        "fp": 1,
        "fn": 1,
    }
    # Dependencies: 3 of 4 captured, ghost claim unverified, delta missing.
    assert result["metrics"]["module_dependencies"] == {
        "precision": pytest.approx(0.75),
        "recall": pytest.approx(0.75),
        "f1": pytest.approx(0.75),
        "tp": 3,
        "fp": 1,
        "fn": 1,
    }
    assert result["metrics"]["symbol_imports"]["f1"] == pytest.approx(1.0)

    assert result["details"]["phantom_module_nodes"] == ["pkg/ghost.py"]
    assert result["details"]["missing_module_nodes"] == ["pkg/sub/__init__.py"]
    assert result["details"]["missing_module_dependencies"] == [
        "pkg/alpha.py -> pkg/delta.py"
    ]
    assert result["details"]["unverified_import_edges"] == [
        "pkg/alpha.py -> pkg/ghost.py"
    ]


def test_symbol_import_requires_target_module_evidence(tmp_path: Path) -> None:
    """A targetless symbol node is not a wildcard for its defining module."""

    tree = tmp_path / "src"
    _write_tree(tree)
    gold = extract_gold(tree)
    graph = _graph_fixture()
    helper = next(node for node in graph["nodes"] if node["id"] == "helper")
    helper.pop("source_file")

    result = evaluate_structure(gold, graph)

    assert result["metrics"]["symbol_imports"]["tp"] == 0
    assert result["metrics"]["symbol_imports"]["fn"] == 1
    assert result["metrics"]["symbol_imports"]["f1"] == pytest.approx(0.0)


def test_structeval_cli_smoke(tmp_path: Path) -> None:
    tree = tmp_path / "src"
    _write_tree(tree)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph_fixture()), encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = bench_main(
        [
            "structeval",
            "--graph",
            str(graph_path),
            "--source-tree",
            str(tree),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    result = json.loads(
        (output_dir / "structeval_result.json").read_text(encoding="utf-8")
    )
    assert result["schema_version"] == 1
    assert result["kind"] == "structural"
    report = (output_dir / "structural_report.md").read_text(encoding="utf-8")
    assert "Structural Evaluation" in report
    assert "Module dependency edges" in report


def test_evaluate_structure_is_deterministic(tmp_path: Path) -> None:
    tree = tmp_path / "src"
    _write_tree(tree)
    gold = extract_gold(tree)

    assert evaluate_structure(gold, _graph_fixture()) == evaluate_structure(
        gold, _graph_fixture()
    )


def test_emit_queries_and_transition_diff(tmp_path: Path) -> None:
    tree = tmp_path / "src"
    _write_tree(tree)
    gold = extract_gold(tree)
    baseline = evaluate_structure(gold, _graph_fixture())

    queries_path = tmp_path / "queries.jsonl"
    count = emit_queries(baseline, queries_path)
    lines = [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert count == len(lines) == 1
    assert lines[0]["gold"] == "pkg/alpha.py -> pkg/delta.py"
    assert "depend on" in lines[0]["query"]

    # A "refined" graph recovers the missing dependency and drops the
    # ghost claim — the transition diff must see exactly that.
    fixed = json.loads(json.dumps(_graph_fixture()))
    fixed["links"] = [
        link for link in fixed["links"] if link["target"] != "ghost"
    ]
    fixed["links"].append({"source": "alpha", "target": "delta", "relation": "imports"})
    candidate = evaluate_structure(gold, fixed)

    transitions = compare_runs(baseline, candidate)
    assert transitions["module_dependencies"]["recovered_0_to_1"] == [
        "pkg/alpha.py -> pkg/delta.py"
    ]
    assert transitions["module_dependencies"]["still_missing"] == []
    assert transitions["unverified_import_edges"]["resolved"] == [
        "pkg/alpha.py -> pkg/ghost.py"
    ]
    assert transitions["unverified_import_edges"]["new_unverified"] == []


def test_default_output_dirs_are_repo_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output defaults anchor to the checkout, not to the caller's cwd."""

    monkeypatch.chdir(tmp_path)

    assert benchmark_cli.EVAL_ROOT == _repo_root / "eval"
    assert benchmark_cli.REPO_ROOT == _repo_root
    assert benchmark_cli.RESULTS_DIR == _repo_root / "eval" / "results"
    assert benchmark_cli.DATA_DIR == _repo_root / "eval" / "data"

    assert benchmark_cli._default_prepare_dir("synthetic-smoke-v1") == (
        benchmark_cli.DATA_DIR / "prepared" / "synthetic-smoke-v1"
    )
    assert benchmark_cli._default_evaluate_dir("synthetic-smoke-v1") == (
        benchmark_cli.RESULTS_DIR / "suite" / "synthetic-smoke-v1"
    )
    assert benchmark_cli._default_structeval_dir(None, None) == (
        benchmark_cli.RESULTS_DIR / "structeval" / "v0.2.0"
    )
    assert benchmark_cli._default_structeval_dir(None, str(tmp_path)).name == "local"
    assert benchmark_cli._default_structeval_dir("v0.3.0", None).name == "v0.3.0"
    assert benchmark_cli._default_report_path() == (
        benchmark_cli.RESULTS_DIR / "report.md"
    )


def test_structeval_defaults_write_under_results_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare structeval writes under RESULTS_DIR even from an unrelated cwd."""

    tree = tmp_path / "src"
    _write_tree(tree)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph_fixture()), encoding="utf-8")

    results_root = tmp_path / "results-root"
    monkeypatch.setattr(benchmark_cli, "RESULTS_DIR", results_root)
    (tmp_path / "unrelated-cwd").mkdir()
    monkeypatch.chdir(tmp_path / "unrelated-cwd")

    exit_code = bench_main(
        [
            "structeval",
            "--graph",
            str(graph_path),
            "--source-tree",
            str(tree),
            "--emit-queries",
        ]
    )

    assert exit_code == 0
    output_dir = results_root / "structeval" / "local"
    assert (output_dir / "structeval_result.json").is_file()
    assert (output_dir / "structural_report.md").is_file()
    queries = (output_dir / "refine-queries.jsonl").read_text(encoding="utf-8")
    assert "pkg/alpha.py -> pkg/delta.py" in queries
