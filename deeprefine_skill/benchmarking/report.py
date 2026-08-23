"""Markdown rendering for benchmark result JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


def _percent(value: object) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{100.0 * value:.2f}%"


def _delta(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{100.0 * value:+.2f} pp"


def _rows(result: Mapping[str, Any]) -> list[tuple[str, str, object, object, object]]:
    suite_label = (
        f"{result['suite']['suite_id']} "
        f"({result['suite']['profile']}, n={result['suite']['case_count']})"
    )
    metrics = result["metrics"]
    rows: list[tuple[str, str, object, object, object]] = []
    definitions = (
        ("intrinsic", "entity_f1", "Entity F1"),
        ("intrinsic", "strict_triple_f1", "Strict Triple F1"),
        ("intrinsic", "g_bleu_f1", "G-BLEU F1"),
        ("intrinsic", "g_rouge_f1", "G-ROUGE F1"),
        ("intrinsic", "g_bertscore_f1", "G-BERTScore F1"),
        ("downstream", "evidence_edge_recall", "Evidence Edge Recall"),
        ("downstream", "complete_path_rate", "Complete Path Rate"),
        ("downstream", "answer_reachability_rate", "Answer Reachability"),
    )
    for category, key, label in definitions:
        baseline_category = metrics["baseline"].get(category)
        candidate_category = metrics["candidate"].get(category)
        if not baseline_category or not candidate_category:
            continue
        baseline = baseline_category["macro"].get(key)
        candidate = candidate_category["macro"].get(key)
        if not isinstance(baseline, (int, float)) or not isinstance(
            candidate,
            (int, float),
        ):
            continue
        delta = metrics.get("delta", {}).get(category, {}).get(key)
        rows.append((suite_label, label, baseline, candidate, delta))

    base_prediction = metrics["baseline"].get("downstream", {}).get("prediction") or {}
    candidate_prediction = (
        metrics["candidate"].get("downstream", {}).get("prediction") or {}
    )
    if "answer_f1" in base_prediction and "answer_f1" in candidate_prediction:
        before = base_prediction["answer_f1"]["value"]
        after = candidate_prediction["answer_f1"]["value"]
        rows.append((suite_label, "Answer F1", before, after, after - before))
    return rows


def render_markdown(
    results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> str:
    """Render one or more benchmark results as a README-ready report."""

    materialized = [results] if isinstance(results, Mapping) else list(results)
    lines = [
        "# Lightweight Graph Quality Benchmark",
        "",
        "| Suite | Metric | Graphify Before | DeepRefine After | Δ |",
        "|---|---|---:|---:|---:|",
    ]
    for result in materialized:
        for suite, metric, before, after, delta in _rows(result):
            lines.append(
                f"| {suite} | {metric} | {_percent(before)} | "
                f"{_percent(after)} | {_delta(delta)} |"
            )

    lines.extend(["", "## Reproducibility", ""])
    for result in materialized:
        environment = result.get("environment", {})
        cost = result.get("cost", {})
        lines.extend(
            [
                f"- `{result['suite']['suite_id']}` v{result['suite']['suite_version']}: "
                f"baseline `{result['inputs']['baseline_graph']['sha256'][:12]}`, "
                f"candidate `{result['inputs']['candidate_graph']['sha256'][:12]}`; "
                f"Graphify `{environment.get('graphify_version') or 'not recorded'}`, "
                f"DeepRefine `{environment.get('deeprefine_version') or 'not recorded'}`, "
                f"model `{environment.get('model') or 'not run'}`; "
                f"{cost.get('llm_calls', 0)} LLM calls.",
            ]
        )

    lines.extend(
        [
            "",
            "> This is a deterministic micro-benchmark for regression checks and "
            "README demonstrations. It does not replace a full GraphRAG evaluation. "
            "2Wiki evidence metrics measure query-relevant path coverage, not "
            "full-graph precision.",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(
    results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    output: str | Path,
) -> Path:
    """Render and write a UTF-8 Markdown report."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(results), encoding="utf-8")
    return output_path
