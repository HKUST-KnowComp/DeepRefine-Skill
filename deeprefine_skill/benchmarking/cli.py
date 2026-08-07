"""Argument-parser integration for ``deeprefine benchmark``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .evaluator import evaluate_suite
from .prepare import SUPPORTED_SUITES, prepare_suite
from .report import render_markdown


def _fail(exc: Exception) -> int:
    print(f"benchmark: {exc}", file=sys.stderr)
    return 2


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def cmd_benchmark_prepare(args: argparse.Namespace) -> int:
    """Prepare a deterministic suite from an official upstream data file."""

    try:
        profile = args.profile or (
            "smoke" if args.suite == "synthetic-smoke-v1" else "quick"
        )
        destination = prepare_suite(
            args.suite,
            profile,
            args.output_dir,
            source=args.source,
        )
    except (OSError, ValueError) as exc:
        return _fail(exc)
    print(f"Prepared benchmark suite: {destination}")
    print(f"Suite manifest: {destination / 'suite.json'}")
    return 0


def _metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "graphify_version": args.graphify_version,
        "deeprefine_version": args.deeprefine_version,
        "model": args.model,
        "temperature": args.temperature,
        "prompt_config_hash": args.prompt_config_hash,
        "llm_calls": args.llm_calls,
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
    }


def cmd_benchmark_evaluate(args: argparse.Namespace) -> int:
    """Evaluate a graph pair and write result.json plus report.md."""

    try:
        result = evaluate_suite(
            args.suite,
            args.baseline_graph,
            args.candidate_graph,
            baseline_predictions=args.baseline_predictions,
            candidate_predictions=args.candidate_predictions,
            baseline_wiki=args.baseline_wiki,
            candidate_wiki=args.candidate_wiki,
            semantic_model=args.semantic_model,
            metadata=_metadata(args),
        )
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        result_path = output_dir / "result.json"
        report_path = output_dir / "report.md"
        _write_json(result_path, result)
        report_path.write_text(render_markdown(result), encoding="utf-8")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _fail(exc)
    print(f"Benchmark result: {result_path}")
    print(f"Markdown report: {report_path}")
    return 0


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    """Merge one or more result JSON files into a Markdown report."""

    results: list[dict[str, Any]] = []
    try:
        for value in args.result:
            path = Path(value)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
                raise ValueError(f"Unsupported benchmark result: {path}")
            results.append(loaded)
        markdown = render_markdown(results)
        if args.output == "-":
            print(markdown, end="")
        else:
            output = Path(args.output).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(markdown, encoding="utf-8")
            print(f"Markdown report: {output}")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _fail(exc)
    return 0


def register_benchmark_commands(subparsers: Any) -> None:
    """Register the benchmark command group on an argparse subparser action."""

    parser = subparsers.add_parser(
        "benchmark",
        help="Prepare and evaluate lightweight graph-quality benchmarks",
    )
    commands = parser.add_subparsers(dest="benchmark_cmd", required=True)

    prepare = commands.add_parser(
        "prepare",
        help="Prepare a deterministic suite from upstream data",
    )
    prepare.add_argument("--suite", required=True, choices=sorted(SUPPORTED_SUITES))
    prepare.add_argument(
        "--profile",
        default=None,
        choices=("smoke", "quick", "readme"),
        help="Default: smoke for synthetic, quick for real suites",
    )
    prepare.add_argument(
        "--source",
        default=None,
        help="Official upstream JSON file (not needed for synthetic-smoke-v1)",
    )
    prepare.add_argument("--output-dir", required=True)
    prepare.set_defaults(func=cmd_benchmark_prepare)

    evaluate = commands.add_parser(
        "evaluate",
        help="Compare baseline and candidate Graphify graph.json files",
    )
    evaluate.add_argument(
        "--suite",
        required=True,
        help="Prepared suite directory, suite.json, or built-in suite ID",
    )
    evaluate.add_argument("--baseline-graph", required=True)
    evaluate.add_argument("--candidate-graph", required=True)
    evaluate.add_argument("--baseline-predictions", default=None)
    evaluate.add_argument("--candidate-predictions", default=None)
    evaluate.add_argument(
        "--baseline-wiki",
        default=None,
        help="Optional baseline Wiki directory for local-link integrity checks",
    )
    evaluate.add_argument(
        "--candidate-wiki",
        default=None,
        help="Optional candidate Wiki directory for local-link integrity checks",
    )
    evaluate.add_argument(
        "--semantic-model",
        default=None,
        help="Opt in to G-BERTScore with this bert-score model (for example roberta-large)",
    )
    evaluate.add_argument("--output-dir", required=True)
    evaluate.add_argument("--graphify-version", default=None)
    evaluate.add_argument("--deeprefine-version", default=None)
    evaluate.add_argument("--model", default=None)
    evaluate.add_argument("--temperature", type=float, default=None)
    evaluate.add_argument("--prompt-config-hash", default=None)
    evaluate.add_argument("--llm-calls", type=int, default=0)
    evaluate.add_argument("--input-tokens", type=int, default=0)
    evaluate.add_argument("--output-tokens", type=int, default=0)
    evaluate.set_defaults(func=cmd_benchmark_evaluate)

    report = commands.add_parser(
        "report",
        help="Render one or more result.json files as Markdown",
    )
    report.add_argument("--result", action="append", required=True)
    report.add_argument("--format", choices=("markdown",), default="markdown")
    report.add_argument("--output", required=True, help="Output file or '-' for stdout")
    report.set_defaults(func=cmd_benchmark_report)
