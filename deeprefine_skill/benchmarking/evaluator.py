"""Intrinsic and downstream evaluation for prepared benchmark suites."""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from deeprefine_skill import __version__

from .graph import (
    GraphData,
    GraphNode,
    align_entities,
    bounded_bfs,
    canonical_edge,
    load_graphify_graph,
    normalize_relation,
    normalize_text,
    source_matches,
)
from .metrics import (
    answer_exact_match,
    answer_token_f1,
    bertscore_graph_score,
    hit_at_k,
    lexical_graph_score,
    precision_recall_f1,
    reciprocal_rank,
    supporting_recall,
    triple_sentence,
)
from .suite import load_predictions, load_suite, sha256_file
from .wiki import inspect_wiki_directory


def _list_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    return [str(value)]


def _gold_nodes(case: Mapping[str, Any]) -> list[GraphNode]:
    result: list[GraphNode] = []
    for index, item in enumerate(case.get("gold_entities", [])):
        if not isinstance(item, Mapping):
            raise ValueError(f"{case['id']}: gold_entities[{index}] must be an object")
        node_id = str(item.get("id", "")).strip()
        if not node_id:
            raise ValueError(f"{case['id']}: gold_entities[{index}] is missing id")
        result.append(
            GraphNode(
                id=node_id,
                label=str(item.get("label", node_id)),
                aliases=tuple(_list_strings(item.get("aliases"))),
                source_file=str(item.get("source_file", "")),
                data=dict(item),
            )
        )
    return result


def _scope_node_ids(
    case: Mapping[str, Any],
    graph: GraphData,
    aligned_predicted_ids: Iterable[str],
    *,
    only_intrinsic_case: bool,
) -> set[str]:
    sources = _list_strings(case.get("source_files"))
    source_scoped = {
        node.id
        for node in graph.nodes.values()
        if node.source_file
        and any(source_matches(node.source_file, source) for source in sources)
    }
    if source_scoped:
        return source_scoped.union(aligned_predicted_ids)
    if only_intrinsic_case:
        return set(graph.nodes)
    return set(aligned_predicted_ids)


def _edge_relation_options(item: Mapping[str, Any]) -> set[str]:
    values = [item.get("relation", ""), *_list_strings(item.get("accepted_relations"))]
    return {normalize_relation(value) for value in values if normalize_relation(value)}


def _gold_edge_records(
    case: Mapping[str, Any],
    *,
    directed: bool,
) -> list[tuple[str, str, str, set[str]]]:
    records: list[tuple[str, str, str, set[str]]] = []
    for index, item in enumerate(case.get("gold_edges", [])):
        if not isinstance(item, Mapping):
            raise ValueError(f"{case['id']}: gold_edges[{index}] must be an object")
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        relations = _edge_relation_options(item)
        if not source or not target or not relations:
            raise ValueError(
                f"{case['id']}: gold_edges[{index}] needs source, relation, and target"
            )
        canonical_source, _, canonical_target = canonical_edge(
            source,
            "",
            target,
            directed=directed,
        )
        primary = normalize_relation(item.get("relation", ""))
        records.append((canonical_source, primary, canonical_target, relations))
    return records


def _intrinsic_case(
    case: Mapping[str, Any],
    graph: GraphData,
    *,
    only_intrinsic_case: bool,
    semantic_model: str | None,
) -> dict[str, Any]:
    gold_nodes = _gold_nodes(case)
    alignment = align_entities(gold_nodes, graph)
    reverse_alignment = {predicted: gold for gold, predicted in alignment.items()}
    scope_ids = _scope_node_ids(
        case,
        graph,
        alignment.values(),
        only_intrinsic_case=only_intrinsic_case,
    )

    gold_entity_ids = {node.id for node in gold_nodes}
    predicted_entity_keys = {
        reverse_alignment.get(node_id, f"predicted::{node_id}") for node_id in scope_ids
    }
    entity_tp = len(gold_entity_ids.intersection(predicted_entity_keys))
    entity_prf = precision_recall_f1(
        entity_tp,
        len(predicted_entity_keys - gold_entity_ids),
        len(gold_entity_ids - predicted_entity_keys),
    )

    directed = bool(case.get("directed", True))
    gold_edges = _gold_edge_records(case, directed=directed)
    predicted_edges: set[tuple[str, str, str]] = set()
    predicted_lexical_by_edge: dict[tuple[str, str, str], str] = {}
    for edge in graph.edges:
        if edge.source not in scope_ids or edge.target not in scope_ids:
            continue
        mapped_source = reverse_alignment.get(edge.source, f"predicted::{edge.source}")
        mapped_target = reverse_alignment.get(edge.target, f"predicted::{edge.target}")
        edge_key = canonical_edge(
            mapped_source,
            edge.relation,
            mapped_target,
            directed=directed,
        )
        predicted_edges.add(edge_key)
        predicted_lexical_by_edge.setdefault(
            edge_key,
            triple_sentence(
                (
                    graph.nodes[edge.source].label,
                    edge.relation,
                    graph.nodes[edge.target].label,
                )
            )
        )

    matched_predicted: set[tuple[str, str, str]] = set()
    matched_gold_indices: set[int] = set()
    for predicted_edge in sorted(predicted_edges):
        for index, (source, _primary, target, relation_options) in enumerate(gold_edges):
            if index in matched_gold_indices:
                continue
            if (
                predicted_edge[0] == source
                and predicted_edge[2] == target
                and predicted_edge[1] in relation_options
            ):
                matched_predicted.add(predicted_edge)
                matched_gold_indices.add(index)
                break

    edge_prf = precision_recall_f1(
        len(matched_predicted),
        len(predicted_edges) - len(matched_predicted),
        len(gold_edges) - len(matched_gold_indices),
    )

    gold_by_id = {node.id: node for node in gold_nodes}
    gold_lexical = [
        triple_sentence(
            (
                gold_by_id[source].label,
                primary,
                gold_by_id[target].label,
            )
        )
        for source, primary, target, _relations in gold_edges
        if source in gold_by_id and target in gold_by_id
    ]

    missing_entities = sorted(gold_entity_ids - set(alignment))
    spurious_entities = sorted(scope_ids - set(reverse_alignment))
    missing_edges = [
        {
            "source": source,
            "relation": primary,
            "target": target,
        }
        for index, (source, primary, target, _relations) in enumerate(gold_edges)
        if index not in matched_gold_indices
    ]
    spurious_edges = [
        {"source": source, "relation": relation, "target": target}
        for source, relation, target in sorted(predicted_edges - matched_predicted)
    ]

    predicted_lexical = [
        predicted_lexical_by_edge[key] for key in sorted(predicted_lexical_by_edge)
    ]
    result = {
        "entity": entity_prf.as_dict(),
        "strict_triple": edge_prf.as_dict(),
        "g_bleu": lexical_graph_score(predicted_lexical, gold_lexical, metric="bleu"),
        "g_rouge": lexical_graph_score(predicted_lexical, gold_lexical, metric="rouge"),
        "alignment": alignment,
        "missing_entities": missing_entities,
        "spurious_entities": spurious_entities,
        "missing_edges": missing_edges,
        "spurious_edges": spurious_edges,
    }
    if semantic_model:
        result["g_bertscore"] = bertscore_graph_score(
            predicted_lexical,
            gold_lexical,
            model_type=semantic_model,
        )
    return result


def _aliases_from_endpoint(value: object) -> list[str]:
    if isinstance(value, Mapping):
        values = [
            value.get("label", ""),
            *_list_strings(value.get("aliases")),
        ]
        return [str(item) for item in values if str(item).strip()]
    return _list_strings(value)


def _edge_is_present(graph: GraphData, item: Mapping[str, Any]) -> bool:
    source_ids = set(graph.node_ids_for_aliases(_aliases_from_endpoint(item.get("source"))))
    target_ids = set(graph.node_ids_for_aliases(_aliases_from_endpoint(item.get("target"))))
    relations = _edge_relation_options(item)
    for edge in graph.edges:
        relation = normalize_relation(edge.relation)
        if relation not in relations:
            continue
        if edge.source in source_ids and edge.target in target_ids:
            return True
        if not graph.directed and edge.target in source_ids and edge.source in target_ids:
            return True
    return False


def _prediction_metrics(
    prediction: Mapping[str, Any] | None,
    case: Mapping[str, Any],
) -> dict[str, float]:
    if not prediction:
        return {}
    result: dict[str, float] = {}
    answers = _list_strings(case.get("answers"))
    if "answer" in prediction and answers:
        result["answer_em"] = answer_exact_match(prediction["answer"], answers)
        result["answer_f1"] = answer_token_f1(prediction["answer"], answers)

    ranked_nodes = _list_strings(prediction.get("retrieved_nodes"))
    answer_entities = _list_strings(case.get("answer_entities")) or answers
    if "retrieved_nodes" in prediction and answer_entities:
        result["hit_at_1"] = hit_at_k(ranked_nodes, answer_entities, 1)
        result["hit_at_5"] = hit_at_k(ranked_nodes, answer_entities, 5)
        result["mrr"] = reciprocal_rank(ranked_nodes, answer_entities)

    retrieved_facts = _list_strings(prediction.get("retrieved_supporting_facts"))
    supporting_facts = _list_strings(case.get("supporting_facts"))
    if "retrieved_supporting_facts" in prediction and supporting_facts:
        result["supporting_fact_recall_at_2"] = supporting_recall(
            retrieved_facts,
            supporting_facts,
            k=2,
        )
        result["supporting_fact_recall_at_5"] = supporting_recall(
            retrieved_facts,
            supporting_facts,
            k=5,
        )
    return result


def _downstream_case(
    case: Mapping[str, Any],
    graph: GraphData,
    prediction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    evidence = case.get("evidence_edges", [])
    if not isinstance(evidence, list):
        raise ValueError(f"{case['id']}: evidence_edges must be an array")
    evidence_hits = [
        bool(isinstance(item, Mapping) and _edge_is_present(graph, item))
        for item in evidence
    ]
    evidence_recall = (
        sum(evidence_hits) / len(evidence_hits) if evidence_hits else 1.0
    )
    complete_path = bool(all(evidence_hits))

    seed_ids = graph.node_ids_for_aliases(_list_strings(case.get("seed_entities")))
    answer_ids = set(
        graph.node_ids_for_aliases(
            _list_strings(case.get("answer_entities"))
            or _list_strings(case.get("answers"))
        )
    )
    max_hops = int(case.get("max_hops", max(1, len(evidence))))
    reachable = bounded_bfs(graph, seed_ids, max_hops)
    answer_reachable = bool(answer_ids.intersection(reachable))

    result: dict[str, Any] = {
        "evidence_edge_recall": evidence_recall,
        "evidence_hits": evidence_hits,
        "evidence_hit_count": sum(evidence_hits),
        "evidence_edge_count": len(evidence_hits),
        "complete_path": complete_path,
        "answer_reachable": answer_reachable,
        "max_hops": max_hops,
    }
    optional_metrics = _prediction_metrics(prediction, case)
    if optional_metrics:
        result["prediction"] = optional_metrics
    return result


def _mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return fmean(materialized) if materialized else None


def _aggregate_side(
    cases: Sequence[Mapping[str, Any]],
    graph: GraphData,
    predictions: Mapping[str, Mapping[str, Any]],
    *,
    semantic_model: str | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    intrinsic_cases = [case for case in cases if case["task"] == "intrinsic"]
    case_results: dict[str, dict[str, Any]] = {}
    for case in cases:
        if case["task"] == "intrinsic":
            case_results[str(case["id"])] = _intrinsic_case(
                case,
                graph,
                only_intrinsic_case=len(intrinsic_cases) == 1,
                semantic_model=semantic_model,
            )
        else:
            case_results[str(case["id"])] = _downstream_case(
                case,
                graph,
                predictions.get(str(case["id"])),
            )

    summary: dict[str, Any] = {"diagnostics": dict(graph.diagnostics)}
    if intrinsic_cases:
        intrinsic_results = [
            case_results[str(case["id"])] for case in intrinsic_cases
        ]
        entity_tp = sum(item["entity"]["tp"] for item in intrinsic_results)
        entity_fp = sum(item["entity"]["fp"] for item in intrinsic_results)
        entity_fn = sum(item["entity"]["fn"] for item in intrinsic_results)
        edge_tp = sum(item["strict_triple"]["tp"] for item in intrinsic_results)
        edge_fp = sum(item["strict_triple"]["fp"] for item in intrinsic_results)
        edge_fn = sum(item["strict_triple"]["fn"] for item in intrinsic_results)
        summary["intrinsic"] = {
            "case_count": len(intrinsic_results),
            "macro": {
                "entity_f1": _mean(item["entity"]["f1"] for item in intrinsic_results),
                "strict_triple_f1": _mean(
                    item["strict_triple"]["f1"] for item in intrinsic_results
                ),
                "g_bleu_f1": _mean(item["g_bleu"]["f1"] for item in intrinsic_results),
                "g_rouge_f1": _mean(
                    item["g_rouge"]["f1"] for item in intrinsic_results
                ),
            },
            "micro": {
                "entity": precision_recall_f1(entity_tp, entity_fp, entity_fn).as_dict(),
                "strict_triple": precision_recall_f1(
                    edge_tp,
                    edge_fp,
                    edge_fn,
                ).as_dict(),
            },
        }
        if semantic_model:
            summary["intrinsic"]["macro"]["g_bertscore_f1"] = _mean(
                item["g_bertscore"]["f1"] for item in intrinsic_results
            )

    downstream_cases = [case for case in cases if case["task"] == "downstream"]
    if downstream_cases:
        downstream_results = [
            case_results[str(case["id"])] for case in downstream_cases
        ]
        evidence_hits = sum(item["evidence_hit_count"] for item in downstream_results)
        evidence_total = sum(item["evidence_edge_count"] for item in downstream_results)
        prediction_names = sorted(
            {
                name
                for item in downstream_results
                for name in item.get("prediction", {})
            }
        )
        prediction_summary: dict[str, Any] = {}
        for name in prediction_names:
            values = [
                item["prediction"][name]
                for item in downstream_results
                if name in item.get("prediction", {})
            ]
            prediction_summary[name] = {
                "value": _mean(values),
                "evaluated_cases": len(values),
            }
        summary["downstream"] = {
            "case_count": len(downstream_results),
            "macro": {
                "evidence_edge_recall": _mean(
                    item["evidence_edge_recall"] for item in downstream_results
                ),
                "complete_path_rate": _mean(
                    float(item["complete_path"]) for item in downstream_results
                ),
                "answer_reachability_rate": _mean(
                    float(item["answer_reachable"]) for item in downstream_results
                ),
            },
            "micro": {
                "evidence_edge_recall": (
                    evidence_hits / evidence_total if evidence_total else 1.0
                ),
                "evidence_hit_count": evidence_hits,
                "evidence_edge_count": evidence_total,
            },
            "prediction": prediction_summary or None,
        }
    return summary, case_results


def _headline_delta(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in ("intrinsic", "downstream"):
        if category not in baseline or category not in candidate:
            continue
        base_macro = baseline[category].get("macro", {})
        candidate_macro = candidate[category].get("macro", {})
        result[category] = {
            name: candidate_macro[name] - base_macro[name]
            for name in sorted(set(base_macro).intersection(candidate_macro))
            if isinstance(base_macro[name], (int, float))
            and isinstance(candidate_macro[name], (int, float))
        }
    return result


def _transitions(
    cases: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    counts = {"0_to_1": 0, "1_to_0": 0, "1_to_1": 0, "0_to_0": 0}
    for case in cases:
        if case["task"] != "downstream":
            continue
        case_id = str(case["id"])
        before = int(bool(baseline[case_id]["complete_path"]))
        after = int(bool(candidate[case_id]["complete_path"]))
        counts[f"{before}_to_{after}"] += 1
    total = sum(counts.values())
    return {
        "complete_path": {
            "counts": counts,
            "rates": {
                name: count / total if total else 0.0
                for name, count in counts.items()
            },
        }
    }


def _case_delta(
    task: str,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, float]:
    if task == "intrinsic":
        return {
            "entity_f1": candidate["entity"]["f1"] - baseline["entity"]["f1"],
            "strict_triple_f1": (
                candidate["strict_triple"]["f1"] - baseline["strict_triple"]["f1"]
            ),
            "g_bleu_f1": candidate["g_bleu"]["f1"] - baseline["g_bleu"]["f1"],
            "g_rouge_f1": candidate["g_rouge"]["f1"] - baseline["g_rouge"]["f1"],
        }
    return {
        "evidence_edge_recall": (
            candidate["evidence_edge_recall"] - baseline["evidence_edge_recall"]
        ),
        "complete_path": float(candidate["complete_path"])
        - float(baseline["complete_path"]),
        "answer_reachable": float(candidate["answer_reachable"])
        - float(baseline["answer_reachable"]),
    }


def evaluate_suite(
    suite_path: str | Path | Mapping[str, Any],
    baseline_graph: str | Path,
    candidate_graph: str | Path,
    *,
    baseline_predictions: str | Path | None = None,
    candidate_predictions: str | Path | None = None,
    baseline_wiki: str | Path | None = None,
    candidate_wiki: str | Path | None = None,
    semantic_model: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate baseline and candidate graphs without modifying either input."""

    started = time.perf_counter()
    suite, _suite_directory = load_suite(suite_path)
    baseline_path = Path(baseline_graph).resolve()
    candidate_path = Path(candidate_graph).resolve()
    before_hashes = {
        "baseline": sha256_file(baseline_path),
        "candidate": sha256_file(candidate_path),
    }
    baseline_prediction_hash = (
        sha256_file(baseline_predictions) if baseline_predictions else None
    )
    candidate_prediction_hash = (
        sha256_file(candidate_predictions) if candidate_predictions else None
    )

    baseline_data = load_graphify_graph(baseline_path)
    candidate_data = load_graphify_graph(candidate_path)
    baseline_prediction_data = load_predictions(baseline_predictions)
    candidate_prediction_data = load_predictions(candidate_predictions)
    cases = suite["cases"]
    baseline_summary, baseline_cases = _aggregate_side(
        cases,
        baseline_data,
        baseline_prediction_data,
        semantic_model=semantic_model,
    )
    candidate_summary, candidate_cases = _aggregate_side(
        cases,
        candidate_data,
        candidate_prediction_data,
        semantic_model=semantic_model,
    )
    if baseline_wiki:
        baseline_summary["wiki"] = inspect_wiki_directory(baseline_wiki)
    if candidate_wiki:
        candidate_summary["wiki"] = inspect_wiki_directory(candidate_wiki)

    after_hashes = {
        "baseline": sha256_file(baseline_path),
        "candidate": sha256_file(candidate_path),
    }
    if before_hashes != after_hashes:
        raise RuntimeError("Benchmark input graph changed during evaluation")

    case_results = [
        {
            "case_id": str(case["id"]),
            "task": case["task"],
            "baseline": baseline_cases[str(case["id"])],
            "candidate": candidate_cases[str(case["id"])],
            "delta": _case_delta(
                str(case["task"]),
                baseline_cases[str(case["id"])],
                candidate_cases[str(case["id"])],
            ),
        }
        for case in cases
    ]
    source = suite.get("source") if isinstance(suite.get("source"), Mapping) else {}
    run_metadata = dict(metadata or {})
    result = {
        "schema_version": 1,
        "suite": {
            "suite_id": suite["suite_id"],
            "suite_version": suite["suite_version"],
            "profile": suite["profile"],
            "source": source,
            "case_count": len(cases),
            "intrinsic_case_count": sum(
                1 for case in cases if case["task"] == "intrinsic"
            ),
            "downstream_case_count": sum(
                1 for case in cases if case["task"] == "downstream"
            ),
        },
        "inputs": {
            "baseline_graph": {
                "path": str(baseline_path),
                "sha256": before_hashes["baseline"],
            },
            "candidate_graph": {
                "path": str(candidate_path),
                "sha256": before_hashes["candidate"],
            },
            "baseline_predictions": {
                "path": str(Path(baseline_predictions).resolve()),
                "sha256": baseline_prediction_hash,
            }
            if baseline_predictions
            else None,
            "candidate_predictions": {
                "path": str(Path(candidate_predictions).resolve()),
                "sha256": candidate_prediction_hash,
            }
            if candidate_predictions
            else None,
            "baseline_wiki": str(Path(baseline_wiki).resolve())
            if baseline_wiki
            else None,
            "candidate_wiki": str(Path(candidate_wiki).resolve())
            if candidate_wiki
            else None,
        },
        "environment": {
            "deeprefine_skill_version": __version__,
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "graphify_version": run_metadata.get("graphify_version"),
            "deeprefine_version": run_metadata.get("deeprefine_version"),
            "model": run_metadata.get("model"),
            "temperature": run_metadata.get("temperature"),
            "prompt_config_hash": run_metadata.get("prompt_config_hash"),
            "semantic_model": semantic_model,
        },
        "cost": {
            "llm_calls": int(run_metadata.get("llm_calls") or 0),
            "input_tokens": int(run_metadata.get("input_tokens") or 0),
            "output_tokens": int(run_metadata.get("output_tokens") or 0),
        },
        "metrics": {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "delta": _headline_delta(baseline_summary, candidate_summary),
        },
        "transitions": _transitions(cases, baseline_cases, candidate_cases),
        "cases": case_results,
        "runtime": {
            "evaluation_seconds": time.perf_counter() - started,
        },
    }
    return result
