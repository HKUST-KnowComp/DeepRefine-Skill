from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from atlas_rag.llm_generator import GenerationConfig, LLMGenerator
from atlas_rag.vectorstore.embedding_model import Qwen3Emb
from autorefiner.src.reafiner import Reafiner, RetrievalStepResult

from .adapter_graphify import (
    load_or_build_data,
    save_bundle,
    save_graphify_json,
    sync_kg_to_graphify,
)
from .history import append_history, mark_refined, query_id


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
    encoder = Qwen3Emb(embed_client)
    return llm, encoder


def run_refine(
    *,
    graph_path: Path,
    cache_pkl: Path,
    backup_path: Path,
    history_path: Path,
    log_dir: Path,
    cfg: dict[str, str],
    queries: list[dict[str, Any]],
    rebuild_index: bool = False,
    base_top_k: int = 5,
    max_hops: int = 4,
) -> dict[str, Any]:
    if not graph_path.is_file():
        raise FileNotFoundError(f"graphify graph not found: {graph_path}")

    llm, encoder = make_clients(cfg)
    raw, data = load_or_build_data(
        graph_path, cache_pkl, encoder, rebuild=rebuild_index
    )

    reafiner = Reafiner(
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

    def _persist() -> None:
        if completed == 0:
            return
        data["KG"] = reafiner.kg
        nonlocal raw
        raw = sync_kg_to_graphify(raw, reafiner.kg)
        save_graphify_json(graph_path, raw, backup_path=backup_path)
        save_bundle(cache_pkl, raw, data)
        mark_refined(history_path, refined_ids)

    try:
        with log_path.open("w", encoding="utf-8") as log_f:
            for sample in queries:
                query = sample["query"]
                qid = query_id(query, sample.get("id"))
                print(f"\n=== [{qid}] {query}")
                final_answer, _, refinement_result = reafiner.refine(query=query)
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
                    }
                )
                refined_ids.add(qid)
                completed += 1
                print(
                    f"  steps={n_steps}, nodes={reafiner.kg.number_of_nodes()}, "
                    f"edges={reafiner.kg.number_of_edges()}"
                )
    finally:
        _persist()

    return {
        "log_path": str(log_path),
        "graph_path": str(graph_path),
        "nodes": reafiner.kg.number_of_nodes(),
        "edges": reafiner.kg.number_of_edges(),
        "queries_processed": len(queries),
        "summary": summary_rows,
    }


def refine_from_history(
    paths: dict[str, Path],
    cfg: dict[str, str],
    *,
    query: str | None = None,
    rebuild_index: bool = False,
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
        cache_pkl=paths["reafiner_pkl"],
        backup_path=paths["graph_backup"],
        history_path=paths["history"],
        log_dir=paths["graphify_out"] / ".deeprefine",
        cfg=cfg,
        queries=queries,
        rebuild_index=rebuild_index,
    )
