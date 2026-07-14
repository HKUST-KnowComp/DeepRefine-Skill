"""Validate agent-native refinement loop traces (same control flow as DeepRefine.refine())."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from deeprefine_skill.agent_prompts import (
    HISTORY_HORIZON_DEFAULT,
    MAX_HOPS_DEFAULT,
    MAX_TRIPLE_NUM_BY_STEP,
)
from deeprefine_skill.history import query_id

JUDGE_RE = re.compile(r"<judge>\s*(yes|no)\s*</judge>", re.IGNORECASE)
ABDUCTION_RE = re.compile(r"<abduction>.*?</abduction>", re.IGNORECASE | re.DOTALL)
REFINEMENT_RE = re.compile(r"<refinement>.*?</refinement>", re.IGNORECASE | re.DOTALL)

REQUIRED_STEP_KEYS = (
    "step",
    "num_hops",
    "base_top_k",
    "query",
    "retrieved_subgraph",
    "answerable",
    "judgement_raw",
    "retrieval",
)

REQUIRED_RETRIEVAL_KEYS = ("method", "evidence")


def load_trace(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_trace(path: Path, trace: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_trace(query: str) -> dict[str, Any]:
    q = query.strip()
    return {
        "schema_version": 1,
        "mode": "agent-loop",
        "query": q,
        "query_id": query_id(q),
        "constants": {
            "max_hops": MAX_HOPS_DEFAULT,
            "increment_hop": 1,
            "base_top_k": 10,
            "max_triple_num_by_step": list(MAX_TRIPLE_NUM_BY_STEP),
            "history_horizon_size": HISTORY_HORIZON_DEFAULT,
        },
        "interaction_history": [],
        "error_abduction_reason": None,
        "error_abduction_raw": None,
        "refinement_action_file": None,
        "early_exit": None,
    }


def parse_judge(judgement_raw: str) -> bool | None:
    m = JUDGE_RE.search(judgement_raw or "")
    if not m:
        return None
    return m.group(1).strip().lower().startswith("yes")


def format_interaction_history_for_abduction(
    interaction_history: list[dict[str, Any]],
    *,
    horizon: int = HISTORY_HORIZON_DEFAULT,
) -> str:
    """Same layout as DeepRefine._error_abduction."""
    rows = interaction_history[-horizon:]
    parts: list[str] = []
    for i, result in enumerate(rows):
        parts.append(
            f"Step{i + 1}:\n"
            f"['Query': {result.get('query')}, "
            f"'Subgraph_hop': {result.get('num_hops')}, "
            f"'Subgraph_content': {str(result.get('retrieved_subgraph'))}, "
            f"'Answerable': {result.get('answerable')}]\n"
        )
    return "\n".join(parts)


def reafiner_early_exit(interaction_history: list[dict[str, Any]]) -> bool:
    """DeepRefine.refine(): len(history) <= 1 → no KG refinement."""
    return len(interaction_history) <= 1


def reafiner_needs_refinement(interaction_history: list[dict[str, Any]]) -> bool:
    return len(interaction_history) > 1


#: Valid retrieval methods for step 1 (initial hop).
#: Extended for LLM-Wiki: wiki_search / wiki_search+k_hop_expansion.
VALID_RETRIEVAL_METHODS_STEP1 = (
    "graphify_query",
    "graphify_query+graph_read",
    "wiki_search",                   # wiki full-text search
    "wiki_search+k_hop_expansion",   # wiki search + BFS
)

#: Valid retrieval methods for hop 2+ (expansion hops).
#: Extended for LLM-Wiki: wiki variants + link_traversal.
VALID_RETRIEVAL_METHODS_HOP2 = (
    "k_hop_expansion",
    "graphify_query",
    "graphify_query+k_hop_expansion",
    "wiki_search",                   # wiki full-text search
    "wiki_search+k_hop_expansion",   # wiki search + BFS
    "link_traversal",                # wiki pure BFS link traversal
)


def validate_trace(trace: dict[str, Any], *, refinement_text: str | None = None) -> list[str]:
    """
    Return human-readable errors. Empty list means the trace matches DeepRefine control flow.
    """
    errors: list[str] = []
    if trace.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if trace.get("mode") != "agent-loop":
        errors.append('mode must be "agent-loop"')

    query = (trace.get("query") or "").strip()
    if not query:
        errors.append("missing query")

    ih: list[dict[str, Any]] = trace.get("interaction_history") or []
    if not ih:
        errors.append("interaction_history is empty — run hops 1..N before apply/finish")
        return errors

    max_hops = int((trace.get("constants") or {}).get("max_hops", MAX_HOPS_DEFAULT))
    if len(ih) > max_hops:
        errors.append(f"interaction_history has {len(ih)} steps; max_hops={max_hops}")

    caps = (trace.get("constants") or {}).get("max_triple_num_by_step") or MAX_TRIPLE_NUM_BY_STEP

    for idx, step in enumerate(ih):
        step_no = idx + 1
        for key in REQUIRED_STEP_KEYS:
            if key not in step:
                errors.append(f"step {step_no}: missing field {key!r}")

        retrieval = step.get("retrieval") or {}
        for key in REQUIRED_RETRIEVAL_KEYS:
            if key not in retrieval or not str(retrieval.get(key) or "").strip():
                errors.append(f"step {step_no}: retrieval.{key} required (graphify command or graph read)")

        subgraph = step.get("retrieved_subgraph") or []
        if not isinstance(subgraph, list) or not subgraph:
            errors.append(f"step {step_no}: retrieved_subgraph must be a non-empty list")
        else:
            cap = caps[min(step_no - 1, len(caps) - 1)] if caps else 20
            if len(subgraph) > cap + 2:
                errors.append(
                    f"step {step_no}: {len(subgraph)} triples exceeds cap ~{cap} "
                    f"(max_triple_num_by_step)"
                )
            for t in subgraph[:3]:
                if not all(k in t for k in ("subject", "relation", "object")):
                    errors.append(f"step {step_no}: triples need subject/relation/object")
                    break

        raw = step.get("judgement_raw") or ""
        parsed = parse_judge(raw)
        if parsed is None:
            errors.append(
                f"step {step_no}: judgement_raw must contain <judge>Yes</judge> or <judge>No</judge>"
            )
        elif parsed != step.get("answerable"):
            errors.append(
                f"step {step_no}: answerable={step.get('answerable')} disagrees with <judge> tag"
            )

        if step.get("answerable") is True and idx < len(ih) - 1:
            errors.append(
                f"step {step_no}: answerable=True but loop continued — stop after <judge>Yes</judge>"
            )

        if step_no == 1:
            if retrieval.get("method") not in VALID_RETRIEVAL_METHODS_STEP1:
                errors.append(
                    f"step {step_no}: retrieval.method must be one of "
                    f"{VALID_RETRIEVAL_METHODS_STEP1}"
                )
        elif step_no > 1:
            if retrieval.get("method") not in VALID_RETRIEVAL_METHODS_HOP2:
                errors.append(
                    f"step {step_no}: retrieval.method must be one of "
                    f"{VALID_RETRIEVAL_METHODS_HOP2}"
                )

    last = ih[-1]
    early = reafiner_early_exit(ih)
    trace_early = trace.get("early_exit")
    if trace_early is not None and trace_early != early:
        errors.append(f"early_exit={trace_early} but DeepRefine rule gives {early}")

    if early:
        if not last.get("answerable"):
            errors.append("early_exit: single hop must end with answerable=True")
        if trace.get("error_abduction_raw") or trace.get("error_abduction_reason"):
            errors.append("early_exit: must not run error abduction")
        if trace.get("refinement_action_file") or refinement_text:
            errors.append("early_exit: must not call deeprefine apply")
    else:
        if not reafiner_needs_refinement(ih):
            errors.append("internal: expected refinement path when len(history)>1")
        ab_raw = trace.get("error_abduction_raw") or ""
        if not ABDUCTION_RE.search(ab_raw):
            errors.append("missing error_abduction_raw with <abduction>...</abduction>")
        if not (trace.get("error_abduction_reason") or "").strip():
            errors.append("missing error_abduction_reason (text inside <abduction>)")

        ref_file = trace.get("refinement_action_file")
        if not ref_file and not refinement_text:
            errors.append("missing refinement_action_file or refinement text for apply")
        if refinement_text and not REFINEMENT_RE.search(refinement_text):
            errors.append("refinement file must contain <refinement>...</refinement>")

    return errors


def trace_path_for_query(deeprefine_dir: Path, q: str) -> Path:
    return deeprefine_dir / f"loop_trace_{query_id(q)}.json"
