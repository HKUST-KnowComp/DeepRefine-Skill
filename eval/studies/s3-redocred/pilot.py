"""Run the bounded Stage 3 Re-DocRED open/closed pilot.

This runner is deliberately separate from the product CLI.  It prepares one
common passage-free graph, supplies source text only through ``original_chunk``
for the open condition, records every API request, enforces hard request caps,
and evaluates strict labels plus newly-added endpoint pairs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from open_closed import (
    DEFAULT_MAX_CONTEXT_CHARS,
    build_refine_kwargs,
    build_run_metadata,
    git_revision,
    prepare_paired_graphs,
    write_run_metadata,
)


DEFAULT_CASE_ID = "redocred-0358d1357783"
SELECTION_SEED = "deeprefine-benchmark-v1"
QUERIES_PER_DOCUMENT = 3
PER_CONDITION_CALL_CAP = 60
PER_CONDITION_LLM_CAP = 20


class PilotStopped(RuntimeError):
    """Raised before an API request when a pilot stop condition is active."""


class UsageRecorder:
    def __init__(self, *, call_cap: int, llm_cap: int) -> None:
        self.call_cap = call_cap
        self.llm_cap = llm_cap
        self.phase = "startup"
        self.records: list[dict[str, Any]] = []

    def before_request(self, kind: str) -> None:
        if any(record.get("error") for record in self.records):
            raise PilotStopped("an earlier API request failed")
        if len(self.records) >= self.call_cap:
            raise PilotStopped(f"condition request cap reached: {self.call_cap}")
        llm_calls = sum(record["kind"] == "llm" for record in self.records)
        if kind == "llm" and llm_calls >= self.llm_cap:
            raise PilotStopped(f"condition LLM request cap reached: {self.llm_cap}")

    def record(
        self,
        *,
        kind: str,
        model: str | None,
        elapsed_s: float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        error: str | None = None,
    ) -> None:
        self.records.append(
            {
                "ts": round(time.time(), 3),
                "phase": self.phase,
                "kind": kind,
                "model": model,
                "elapsed_s": round(elapsed_s, 3),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "error": error,
            }
        )

    def totals(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, int | float]] = {}
        for record in self.records:
            bucket = by_kind.setdefault(
                record["kind"],
                {
                    "calls": 0,
                    "errors": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "elapsed_s": 0.0,
                },
            )
            bucket["calls"] += 1
            bucket["errors"] += int(bool(record["error"]))
            bucket["elapsed_s"] = round(
                float(bucket["elapsed_s"]) + float(record["elapsed_s"] or 0), 3
            )
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                bucket[key] += int(record[key] or 0)
        return {
            "calls": len(self.records),
            "errors": sum(bool(record["error"]) for record in self.records),
            "prompt_tokens": sum(
                int(record["prompt_tokens"] or 0) for record in self.records
            ),
            "completion_tokens": sum(
                int(record["completion_tokens"] or 0) for record in self.records
            ),
            "total_tokens": sum(
                int(record["total_tokens"] or 0) for record in self.records
            ),
            "elapsed_s": round(
                sum(float(record["elapsed_s"] or 0) for record in self.records), 3
            ),
            "by_kind": by_kind,
        }


def _instrument_client(client: Any, recorder: UsageRecorder, *, kind: str) -> None:
    if kind == "llm":
        endpoint = client.chat.completions
    elif kind == "embed":
        endpoint = client.embeddings
    else:
        raise ValueError(f"unsupported request kind: {kind}")
    inner: Callable[..., Any] = endpoint.create

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        recorder.before_request(kind)
        started = time.time()
        try:
            response = inner(*args, **kwargs)
        except Exception as exc:
            recorder.record(
                kind=kind,
                model=kwargs.get("model"),
                elapsed_s=time.time() - started,
                error=type(exc).__name__,
            )
            raise
        usage = getattr(response, "usage", None)
        recorder.record(
            kind=kind,
            model=kwargs.get("model"),
            elapsed_s=time.time() - started,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
        return response

    endpoint.create = wrapped


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _config_from_env() -> dict[str, str]:
    shared_key = os.environ.get("DEEPREFINE_API_KEY", "")
    config = {
        "llm_url": os.environ.get("DEEPREFINE_LLM_URL", "").strip(),
        "embed_url": os.environ.get("DEEPREFINE_EMBED_URL", "").strip(),
        "llm_key": os.environ.get("DEEPREFINE_LLM_API_KEY", shared_key).strip(),
        "embed_key": os.environ.get("DEEPREFINE_EMBED_API_KEY", shared_key).strip(),
        "llm_model": os.environ.get("DEEPREFINE_MODEL", "").strip(),
        "embed_model": os.environ.get("DEEPREFINE_EMBED_MODEL", "").strip(),
    }
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise ValueError(f"missing pilot configuration fields: {', '.join(missing)}")
    return config


def _rank_target(case_id: str, edge: Mapping[str, Any]) -> str:
    key = f"{case_id}|{edge['source']}|{edge['relation']}|{edge['target']}"
    return hashlib.sha256(f"{SELECTION_SEED}:{key}".encode("utf-8")).hexdigest()


def select_targets(
    case_id: str,
    missing_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(missing_edges, key=lambda edge: _rank_target(case_id, edge))[
        :QUERIES_PER_DOCUMENT
    ]


def _serialize_refinement(
    *,
    sample: Mapping[str, Any],
    final_answer: Any,
    result: Any,
) -> dict[str, Any]:
    if result is None:
        return {"sample": dict(sample), "final_answer": final_answer, "result": None}
    history = []
    for step in result.interaction_history:
        history.append(
            {
                "num_hops": getattr(step, "num_hops", None),
                "query": getattr(step, "query", None),
                "retrieved_subgraph": getattr(step, "retrieved_subgraph", None),
                "raw_response": getattr(step, "raw_response", None),
                "answerable": getattr(step, "answerable", None),
            }
        )
    return {
        "sample": dict(sample),
        "final_answer": final_answer,
        "result": {
            "interaction_history": history,
            "error_abduction_reason": result.error_abduction_reason,
            "original_subgraph": result.original_subgraph,
            "refinement_action_raw": result.refinement_action_raw,
            "refinement_action_count": len(result.refinement_action_list),
        },
    }


def fold_exact_baseline_entities(
    kg: Any,
    baseline_labels: Mapping[str, str],
) -> dict[str, Any]:
    """Re-home refinement-minted exact-label duplicates onto baseline nodes.

    DeepRefine hashes action entity strings even when an identically labelled
    graph node already exists.  Stage 3 folds only unique, exact label matches;
    ambiguous and genuinely new entities remain untouched, and relation words
    are never rewritten.
    """

    label_to_ids: dict[str, list[str]] = {}
    for node_id, label in baseline_labels.items():
        label_to_ids.setdefault(str(label).strip(), []).append(node_id)
    fold_map: dict[str, str] = {}
    residual: list[dict[str, str]] = []
    for node_id in list(kg.nodes):
        if node_id in baseline_labels or kg.nodes[node_id].get("type") == "passage":
            continue
        label = str(kg.nodes[node_id].get("id") or node_id).strip()
        candidates = label_to_ids.get(label, [])
        if len(candidates) == 1:
            fold_map[node_id] = candidates[0]
        else:
            residual.append(
                {
                    "key": node_id,
                    "label": label,
                    "reason": "ambiguous" if candidates else "unmatched",
                }
            )

    remapped = 0
    duplicates_dropped = 0
    self_loops_dropped = 0
    incident = [
        (source, target, dict(attributes))
        for source, target, attributes in kg.edges(data=True)
        if source in fold_map or target in fold_map
    ]
    kg.remove_edges_from([(source, target) for source, target, _ in incident])
    for source, target, attributes in incident:
        new_source = fold_map.get(source, source)
        new_target = fold_map.get(target, target)
        if new_source == new_target:
            self_loops_dropped += 1
        elif kg.has_edge(new_source, new_target):
            duplicates_dropped += 1
        else:
            kg.add_edge(new_source, new_target, **attributes)
            remapped += 1
    kg.remove_nodes_from(fold_map)
    return {
        "folded": {
            source: {
                "label": str(kg.nodes[target].get("id") or target),
                "target": target,
            }
            for source, target in fold_map.items()
        },
        "residual": residual,
        "edges_remapped": remapped,
        "edges_duplicated_dropped": duplicates_dropped,
        "edges_self_loop_dropped": self_loops_dropped,
    }


def prepare_pilot_inputs(
    *,
    source_root: Path,
    output_dir: Path,
    case_id: str,
) -> dict[str, Any]:
    suite_path = source_root / "eval/data/prepared/redocred-mini-v1-full/suite.json"
    phase1_path = (
        source_root
        / "eval/results/02-redocred/01-phase1-graph-quality-full50"
        / "redocred-mini-v1-full50/result.json"
    )
    baseline_path = source_root / "eval/data/redocred-extracted/baseline-graph-50doc.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    case = next(item for item in suite["cases"] if item["id"] == case_id)
    case_result = next(item for item in phase1["cases"] if item["case_id"] == case_id)
    source_file = case["source_files"][0]
    source_text = (
        source_root / "eval/data/prepared/redocred-mini-v1-full/corpus" / source_file
    ).read_text(encoding="utf-8")

    nodes = [node for node in baseline["nodes"] if node.get("source_file") == source_file]
    node_ids = {node["id"] for node in nodes}
    links = [
        link
        for link in baseline["links"]
        if link.get("source") in node_ids and link.get("target") in node_ids
    ]
    common_graph = {
        "directed": True,
        "multigraph": False,
        "graph": {
            "study": "s3-redocred-pilot",
            "case_id": case_id,
            "split_from": "baseline-graph-50doc.json",
        },
        "nodes": nodes,
        "links": links,
    }
    open_graph, closed_graph, graph_sha256 = prepare_paired_graphs(common_graph)
    output_dir.mkdir(parents=True, exist_ok=False)
    baseline_out = output_dir / "baseline_graph.json"
    baseline_out.write_text(
        json.dumps(open_graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for mode, graph in (("open", open_graph), ("closed", closed_graph)):
        condition_dir = output_dir / mode
        condition_dir.mkdir()
        (condition_dir / "graph.json").write_text(
            json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    targets = select_targets(case_id, case_result["baseline"]["missing_edges"])
    label_by_id = {entity["id"]: entity["label"] for entity in case["gold_entities"]}
    queries = [
        {
            "id": f"rq-{case_id}-k{index}",
            "query": (
                "According to the document, what is the relationship between "
                f"{label_by_id[edge['source']]} and {label_by_id[edge['target']]}?"
            ),
            "target": edge,
        }
        for index, edge in enumerate(targets)
    ]
    pilot_suite = {**suite, "profile": "pilot-1doc", "cases": [case]}
    (output_dir / "suite.json").write_text(
        json.dumps(pilot_suite, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "queries.json").write_text(
        json.dumps(queries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "case": case,
        "source_file": source_file,
        "source_text": source_text,
        "queries": queries,
        "graph_sha256": graph_sha256,
        "baseline_path": baseline_out,
        "suite_path": output_dir / "suite.json",
    }


def _make_clients(config: Mapping[str, str], recorder: UsageRecorder, *, seed: int) -> tuple[Any, Any]:
    from openai import OpenAI
    from atlas_rag.llm_generator import GenerationConfig, LLMGenerator
    from atlas_rag.vectorstore.embedding_model import Qwen3Emb

    llm_client = OpenAI(
        base_url=config["llm_url"], api_key=config["llm_key"], timeout=300.0
    )
    embed_client = OpenAI(
        base_url=config["embed_url"], api_key=config["embed_key"], timeout=300.0
    )
    _instrument_client(llm_client, recorder, kind="llm")
    _instrument_client(embed_client, recorder, kind="embed")
    generator = LLMGenerator(
        client=llm_client,
        model_name=config["llm_model"],
        default_config=GenerationConfig(
            seed=seed,
            chat_template_kwargs={"enable_thinking": False},
        ),
    )
    encoder = Qwen3Emb(embed_client, model_name=config["embed_model"])
    return generator, encoder


def _write_usage(path: Path, recorder: UsageRecorder) -> dict[str, Any]:
    totals = recorder.totals()
    rows = [*recorder.records, {"kind": "summary", "phase": "done", **totals}]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return totals


def run_condition(
    *,
    mode: str,
    prepared: Mapping[str, Any],
    output_dir: Path,
    config: Mapping[str, str],
    deeprefine_repo: Path,
    skill_repo: Path,
    seed: int,
) -> dict[str, Any]:
    from autorefiner.src.deeprefine import DeepRefine
    from deeprefine_skill.adapter_graphify import load_or_build_data, sync_kg_to_graphify

    condition_dir = output_dir / mode
    graph_path = condition_dir / "graph.json"
    recorder = UsageRecorder(
        call_cap=PER_CONDITION_CALL_CAP,
        llm_cap=PER_CONDITION_LLM_CAP,
    )
    llm, encoder = _make_clients(config, recorder, seed=seed)
    recorder.phase = "index-build"
    raw, data = load_or_build_data(
        graph_path,
        condition_dir / "deeprefine_data.pkl",
        encoder,
        rebuild=True,
    )
    if recorder.totals()["errors"]:
        raise PilotStopped(f"{mode}: API error during index build")
    refiner = DeepRefine(
        data=data,
        sentence_encoder=encoder,
        llm_generator=llm,
        base_top_k=5,
        max_hops=4,
        max_triple_num=20,
        max_triple_num_by_step=[5, 10, 15, 20],
        history_horizon_size=4,
        if_gen_answer=False,
    )

    result_path = condition_dir / "refinement_results.jsonl"
    completed = 0
    try:
        with result_path.open("w", encoding="utf-8") as handle:
            for sample in prepared["queries"]:
                recorder.phase = f"refine:{sample['id']}"
                kwargs = build_refine_kwargs(
                    query=sample["query"],
                    context_mode=mode,
                    source_text=prepared["source_text"],
                    max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
                )
                final_answer, _, result = refiner.refine(**kwargs)
                handle.write(
                    json.dumps(
                        _serialize_refinement(
                            sample=sample,
                            final_answer=final_answer,
                            result=result,
                        ),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()
                completed += 1
                if recorder.totals()["errors"]:
                    raise PilotStopped(f"{mode}: API error in {sample['id']}")
    finally:
        usage = _write_usage(condition_dir / "api_usage.jsonl", recorder)

    baseline_labels = {
        node["id"]: str(node.get("label") or node["id"])
        for node in raw.get("nodes", [])
    }
    fold_report = fold_exact_baseline_entities(refiner.kg, baseline_labels)
    data["KG"] = refiner.kg
    candidate = sync_kg_to_graphify(raw, refiner.kg)
    candidate_path = condition_dir / "candidate_graph.json"
    candidate_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = build_run_metadata(
        case_id=prepared["case"]["id"],
        context_mode=mode,
        source_file=prepared["source_file"],
        source_text=prepared["source_text"],
        graph_sha256=prepared["graph_sha256"],
        code_revisions={
            "deeprefine": git_revision(deeprefine_repo),
            "deeprefine_skill": git_revision(skill_repo),
        },
    )
    metadata.update(
        {
            "seed": seed,
            "models": {
                "llm": config["llm_model"],
                "embedding": config["embed_model"],
            },
            "limits": {
                "condition_calls": PER_CONDITION_CALL_CAP,
                "condition_llm_calls": PER_CONDITION_LLM_CAP,
                "stop_on_first_error": True,
            },
            "queries": copy.deepcopy(prepared["queries"]),
            "queries_completed": completed,
            "usage": usage,
            "entity_fold": fold_report,
        }
    )
    write_run_metadata(condition_dir / "metadata.json", metadata)
    return {"candidate_path": candidate_path, "metadata": metadata}


def _predicted_edges(case_result: Mapping[str, Any], gold_edges: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    missing = {
        (edge["source"], edge["relation"], edge["target"])
        for edge in case_result["missing_edges"]
    }
    present_gold = {
        (edge["source"], edge["relation"], edge["target"])
        for edge in gold_edges
    } - missing
    spurious = {
        (edge["source"], edge["relation"], edge["target"])
        for edge in case_result["spurious_edges"]
    }
    return present_gold | spurious


def target_metrics(
    evaluation: Mapping[str, Any],
    *,
    targets: list[dict[str, Any]],
    gold_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    case = evaluation["cases"][0]
    baseline_edges = _predicted_edges(case["baseline"], gold_edges)
    candidate_edges = _predicted_edges(case["candidate"], gold_edges)
    baseline_pairs = {(source, target) for source, _, target in baseline_edges}
    candidate_pairs = {(source, target) for source, _, target in candidate_edges}
    candidate_missing = {
        (edge["source"], edge["relation"], edge["target"])
        for edge in case["candidate"]["missing_edges"]
    }
    rows = []
    for target in targets:
        key = (target["source"], target["relation"], target["target"])
        pair = (target["source"], target["target"])
        rows.append(
            {
                **target,
                "strict_recovered": key not in candidate_missing,
                "endpoint_pair_added": pair not in baseline_pairs and pair in candidate_pairs,
            }
        )
    return {
        "strict_relation_label": sum(row["strict_recovered"] for row in rows),
        "endpoint_pair_added": sum(row["endpoint_pair_added"] for row in rows),
        "denominator": len(rows),
        "targets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--deeprefine-repo", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    _load_env_file(args.env_file)
    config = _config_from_env()
    skill_repo = Path(__file__).resolve().parents[3]
    for path in (
        skill_repo,
        args.deeprefine_repo / "AutoSchemaKG",
        args.deeprefine_repo,
    ):
        sys.path.insert(0, str(path.resolve()))

    prepared = prepare_pilot_inputs(
        source_root=args.source_root.resolve(),
        output_dir=args.output_dir.resolve(),
        case_id=args.case_id,
    )
    from eval.benchmarking.evaluator import evaluate_suite

    summary: dict[str, Any] = {
        "case_id": args.case_id,
        "seed": args.seed,
        "graph_sha256": prepared["graph_sha256"],
        "conditions": {},
    }
    for mode in ("open", "closed"):
        condition = run_condition(
            mode=mode,
            prepared=prepared,
            output_dir=args.output_dir.resolve(),
            config=config,
            deeprefine_repo=args.deeprefine_repo.resolve(),
            skill_repo=skill_repo,
            seed=args.seed,
        )
        evaluation = evaluate_suite(
            prepared["suite_path"],
            prepared["baseline_path"],
            condition["candidate_path"],
            metadata={
                "context_mode": mode,
                "seed": args.seed,
                "llm_calls": condition["metadata"]["usage"]["by_kind"].get(
                    "llm", {}
                ).get("calls", 0),
            },
        )
        (args.output_dir / mode / "evaluation.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metrics = target_metrics(
            evaluation,
            targets=[sample["target"] for sample in prepared["queries"]],
            gold_edges=prepared["case"]["gold_edges"],
        )
        summary["conditions"][mode] = {
            "usage": condition["metadata"]["usage"],
            "metrics": metrics,
            "evaluation": str(args.output_dir / mode / "evaluation.json"),
        }
        if condition["metadata"]["usage"]["errors"]:
            raise PilotStopped(f"{mode}: recorded API error")

    total_calls = sum(
        condition["usage"]["calls"] for condition in summary["conditions"].values()
    )
    if total_calls > 2 * PER_CONDITION_CALL_CAP:
        raise PilotStopped("paired pilot exceeded the total request cap")
    summary["total_calls"] = total_calls
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
