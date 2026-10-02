from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from atlas_rag.llm_generator import GenerationConfig, LLMGenerator
from atlas_rag.vectorstore.embedding_model import Qwen3Emb
from autorefiner.src.deeprefine import DeepRefine, RetrievalStepResult

from .adapter_graphify import (
    load_or_build_data,
    save_bundle,
    save_graphify_json,
    sync_kg_to_graphify,
)
from .action_review import write_review_files
from .batch_isolation import run_query_isolated
from .history import append_history, mark_refined, query_id
from .paths import checkpoints_metadata_path, create_checkpoint


def refinement_to_jsonable(
    sample: dict[str, Any],
    final_answer: Any,
    refinement_result: Any,
) -> dict[str, Any]:
    base = {"sample": sample, "final_answer": final_answer}
    if refinement_result is None:
        base["refinement_result"] = None
        return base

    hist = []
    for step in refinement_result.interaction_history:
        if isinstance(step, RetrievalStepResult):
            hist.append(
                {
                    "num_hops": step.num_hops,
                    "base_top_k": step.base_top_k,
                    "query": step.query,
                    "retrieved_subgraph": step.retrieved_subgraph,
                    "raw_response": step.raw_response,
                    "answerable": step.answerable,
                    "answer": step.answer,
                }
            )
        else:
            hist.append(str(step))

    base["refinement_result"] = {
        "query": refinement_result.query,
        "history_horizon_size": refinement_result.history_horizon_size,
        "interaction_history": hist,
        "error_abduction_reason": refinement_result.error_abduction_reason,
        "original_subgraph": refinement_result.original_subgraph,
        "refined_subgraph": refinement_result.refined_subgraph,
        "refinement_action_raw": refinement_result.refinement_action_raw,
        "refinement_action_count": len(refinement_result.refinement_action_list),
    }
    return base


def _build_openai_client(*, base_url: str, api_key: str) -> OpenAI:
    kwargs: dict[str, str] = {}
    if base_url:
        kwargs["base_url"] = base_url
    # For local compatible servers (e.g. vLLM) api_key can be empty.
    if api_key:
        kwargs["api_key"] = api_key
    elif base_url:
        kwargs["api_key"] = "EMPTY"
    return OpenAI(**kwargs)


def make_clients(cfg: dict[str, str]) -> tuple[LLMGenerator, Qwen3Emb]:
    llm_client = _build_openai_client(
        base_url=cfg["DEEPREFINE_LLM_URL"],
        api_key=cfg["DEEPREFINE_LLM_API_KEY"],
    )
    embed_client = _build_openai_client(
        base_url=cfg["DEEPREFINE_EMBED_URL"],
        api_key=cfg["DEEPREFINE_EMBED_API_KEY"],
    )
    llm = LLMGenerator(
        client=llm_client,
        model_name=cfg["DEEPREFINE_MODEL"],
        default_config=GenerationConfig(chat_template_kwargs={"enable_thinking": False}),
    )
    encoder = Qwen3Emb(
        embed_client,
        model_name=cfg["DEEPREFINE_EMBED_MODEL"],
    )
    return llm, encoder


def run_refine(
    *,
    graph_path: Path,
    cache_pkl: Path,
    history_path: Path,
    log_dir: Path,
    cfg: dict[str, str],
    queries: list[dict[str, Any]],
    rebuild_index: bool = False,
    base_top_k: int = 5,
    max_hops: int = 4,
    apply: bool = False,
) -> dict[str, Any]:
    if not graph_path.is_file():
        raise FileNotFoundError(f"graphify graph not found: {graph_path}")

    llm, encoder = make_clients(cfg)
    raw, data = load_or_build_data(
        graph_path, cache_pkl, encoder, rebuild=rebuild_index
    )
    original_kg = data["KG"].copy()

    deeprefine = DeepRefine(
        data=data,
        sentence_encoder=encoder,
        llm_generator=llm,
        base_top_k=base_top_k,
        max_hops=max_hops,
        max_triple_num=20,
        max_triple_num_by_step=[5, 10, 15, 20],
        history_horizon_size=4,
        if_gen_answer=False,
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"refinement_results_{int(time.time())}.jsonl"
    refined_ids: set[str] = set()
    summary_rows: list[dict[str, Any]] = []
    completed = 0
    failed = 0
    meta_path = checkpoints_metadata_path(graph_path.parent.parent)

    def _persist() -> None:
        if completed == 0:
            return
        if not apply:
            return
        data["KG"] = deeprefine.kg
        nonlocal raw
        raw = sync_kg_to_graphify(raw, deeprefine.kg)
        # Per-run pre-state backup: graph.json.bak.<next_seq> = graph exactly
        # as it was before this batch of refinements was written (the seq
        # matches the post-state checkpoint created below).
        from deeprefine_skill.paths import load_checkpoint_metadata, run_backup_path

        meta_now = load_checkpoint_metadata(meta_path)
        next_seq = (meta_now[-1]["seq"] if meta_now else 0) + 1
        run_backup = run_backup_path(graph_path.parent.parent, next_seq)
        save_graphify_json(graph_path, raw, backup_path=run_backup)
        save_bundle(cache_pkl, raw, data)
        mark_refined(history_path, refined_ids)
        # Post-state checkpoint: full graph after this batch of refinements.
        if refined_ids:
            latest_qid = sorted(refined_ids)[-1]
            create_checkpoint(graph_path, meta_path, latest_qid, "")

    try:
        with log_path.open("w", encoding="utf-8") as log_f:
            for sample in queries:
                query = sample["query"]
                qid = query_id(query, sample.get("id"))
                print(f"\n=== [{qid}] {query}")
                result, error = run_query_isolated(deeprefine, query)
                if error is not None:
                    failed += 1
                    data["KG"] = deeprefine.kg
                    record = refinement_to_jsonable(sample, None, None)
                    record["error"] = error
                    log_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    log_f.flush()
                    summary_rows.append(
                        {
                            "id": qid,
                            "query": query,
                            "steps": 0,
                            "action_count": 0,
                            "status": "failed",
                            "error": error,
                        }
                    )
                    print(f"  query failed: {error}")
                    continue

                assert result is not None
                final_answer, _, refinement_result = result
                record = refinement_to_jsonable(sample, final_answer, refinement_result)
                log_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                log_f.flush()
                n_steps = (
                    len(refinement_result.interaction_history)
                    if refinement_result is not None
                    else 0
                )
                rr = record.get("refinement_result") or {}
                summary_rows.append(
                    {
                        "id": qid,
                        "query": query,
                        "steps": n_steps,
                        "action_count": rr.get("refinement_action_count", 0),
                        "status": "ok",
                    }
                )
                if apply:
                    refined_ids.add(qid)
                completed += 1
                action_file = None
                review_file = None
                review_count = 0
                if rr.get("refinement_action_raw"):
                    action_file = log_dir / f"proposed_refinement_actions_{qid}.txt"
                    review_file = log_dir / f"proposed_refinement_review_{qid}.md"
                    action_file.write_text(rr["refinement_action_raw"], encoding="utf-8")
                    reviews, _ = write_review_files(
                        graph_path=graph_path,
                        refinement_text=rr["refinement_action_raw"],
                        report_path=review_file,
                        json_path=log_dir / f"proposed_refinement_review_{qid}.json",
                    )
                    review_count = len(reviews)
                    summary_rows[-1]["action_file"] = str(action_file)
                    summary_rows[-1]["review_file"] = str(review_file)
                    summary_rows[-1]["mode"] = "apply" if apply else "dry-run"
                print(
                    f"  steps={n_steps}, nodes={deeprefine.kg.number_of_nodes()}, "
                    f"edges={deeprefine.kg.number_of_edges()}"
                )
                if action_file and review_file:
                    print(
                        f"  proposed_actions={review_count}, action_file={action_file}, "
                        f"review={review_file}"
                    )
                if not apply:
                    data["KG"] = original_kg.copy()
                    deeprefine.kg = data["KG"]
    finally:
        _persist()

    return {
        "log_path": str(log_path),
        "graph_path": str(graph_path),
        "nodes": deeprefine.kg.number_of_nodes(),
        "edges": deeprefine.kg.number_of_edges(),
        "queries_processed": len(queries),
        "queries_succeeded": completed,
        "queries_failed": failed,
        "mode": "apply" if apply else "dry-run",
        "summary": summary_rows,
    }


def refine_from_history(
    paths: dict[str, Path],
    cfg: dict[str, str],
    *,
    query: str | None = None,
    rebuild_index: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    if query:
        entry = append_history(paths["history"], query, source="deeprefine")
        queries = [entry]
    else:
        from .history import pending_queries

        queries = pending_queries(paths["history"])
        if not queries:
            raise SystemExit(
                "No pending queries in history. Use:\n"
                "  deeprefine history add --query '...'\n"
                "  deeprefine refine --query '...'"
            )

    return run_refine(
        graph_path=paths["graph_json"],
        cache_pkl=paths["deeprefine_pkl"],
        history_path=paths["history"],
        log_dir=paths["graphify_out"] / ".deeprefine",
        cfg=cfg,
        queries=queries,
        rebuild_index=rebuild_index,
        apply=apply,
    )
