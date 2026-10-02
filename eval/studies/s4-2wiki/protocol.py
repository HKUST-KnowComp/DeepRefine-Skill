"""Stage 4 corrected pre/post-refinement protocol invariants.

This module deliberately contains no model or embedding calls.  It prepares
three isolated phase directories and validates the records produced by a
phase runner.  The API-backed worker is kept separate so these sequencing
guards can be tested offline.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal


Phase = Literal["baseline-reader", "refinement", "post-reader"]
ResultSource = Literal["reader", "refinement"]


class ProtocolViolation(RuntimeError):
    """Raised when a run no longer represents the corrected experiment."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ReaderConfig:
    """Every reader field that must be identical on the two sides."""

    model: str
    embedding_model: str
    seed: int = 2026
    base_top_k: int = 5
    max_hops: int = 4
    max_triple_num: int = 20
    max_triple_num_by_step: tuple[int, ...] = (5, 10, 15, 20)
    history_horizon_size: int = 4
    retrieval_scope: str = "all"
    answer_temperature: float = 0.0
    reader_top_k: int = 20
    skip_conflict_inserts: bool = False
    skip_action_if_answerable: bool = False
    ground_inserts: bool = True
    ground_mode: str = "both"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_triple_num_by_step",
            tuple(self.max_triple_num_by_step),
        )


@dataclass(frozen=True)
class PhaseRequest:
    phase: Phase
    case_id: str
    question: str
    graph_path: Path
    sandbox: Path
    rebuild_index: bool
    read_only: bool
    reader_config: ReaderConfig | None = None


@dataclass(frozen=True)
class PhaseResult:
    phase: Phase
    source: ResultSource
    graph_hash_before: str
    graph_hash_after: str
    process_id: int
    instance_id: str
    answer: str | None = None
    action_count: int = 0
    reader_config: ReaderConfig | None = None
    index_rebuilt: bool = False
    reader_context_hash: str | None = None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    pre_answer: str
    post_answer: str
    baseline_graph_hash: str
    candidate_graph_hash: str
    graph_diff_summary: dict[str, int]
    action_count: int
    reader_config: ReaderConfig


def _copy_graph(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, destination)


def graph_diff_summary(baseline: Path, candidate: Path) -> dict[str, int]:
    before = json.loads(baseline.read_text(encoding="utf-8"))
    after = json.loads(candidate.read_text(encoding="utf-8"))

    def records(value: dict, key: str) -> set[str]:
        actual = key
        if key == "links" and "links" not in value:
            actual = "edges"
        return {
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in value.get(actual, [])
        }

    before_nodes = records(before, "nodes")
    after_nodes = records(after, "nodes")
    before_links = records(before, "links")
    after_links = records(after, "links")
    return {
        "nodes_before": len(before_nodes),
        "nodes_after": len(after_nodes),
        "nodes_added": len(after_nodes - before_nodes),
        "nodes_removed": len(before_nodes - after_nodes),
        "links_before": len(before_links),
        "links_after": len(after_links),
        "links_added": len(after_links - before_links),
        "links_removed": len(before_links - after_links),
    }


def prepare_case_layout(*, baseline_graph: Path, case_root: Path) -> dict[str, Path]:
    """Create isolated phase sandboxes from one frozen baseline graph."""

    if case_root.exists():
        raise FileExistsError(f"case root already exists: {case_root}")
    if not baseline_graph.is_file():
        raise FileNotFoundError(baseline_graph)

    baseline_reader = case_root / "baseline-reader" / "graph.json"
    refinement = case_root / "refinement" / "graph.json"
    _copy_graph(baseline_graph, baseline_reader)
    _copy_graph(baseline_graph, refinement)
    return {
        "baseline_reader": baseline_reader,
        "refinement": refinement,
        "candidate": case_root / "candidate-graph.json",
        "post_reader": case_root / "post-reader" / "graph.json",
        "manifest": case_root / "protocol-result.json",
    }


def _validate_phase_result(
    request: PhaseRequest,
    result: PhaseResult,
    *,
    expected_hash_before: str | None = None,
) -> None:
    if result.phase != request.phase:
        raise ProtocolViolation(
            f"phase mismatch: requested {request.phase}, got {result.phase}"
        )
    actual_after = sha256_file(request.graph_path)
    if (
        expected_hash_before is not None
        and result.graph_hash_before != expected_hash_before
    ):
        raise ProtocolViolation(f"{request.phase}: wrong input graph was reported")
    if actual_after != result.graph_hash_after:
        raise ProtocolViolation(f"{request.phase}: reported graph hash is stale")
    if request.read_only:
        if result.source != "reader":
            raise ProtocolViolation(
                f"{request.phase}: answer must come from an independent reader run"
            )
        if result.graph_hash_before != result.graph_hash_after:
            raise ProtocolViolation(f"{request.phase}: reader modified its graph")
        if result.answer is None:
            raise ProtocolViolation(f"{request.phase}: reader answer is missing")
        if result.reader_config != request.reader_config:
            raise ProtocolViolation(
                f"{request.phase}: executed reader config differs from request"
            )
        if request.rebuild_index and not result.index_rebuilt:
            raise ProtocolViolation(f"{request.phase}: index was not rebuilt")
    elif result.source != "refinement":
        raise ProtocolViolation("refinement phase returned a reader result")


def execute_case(
    *,
    case_id: str,
    question: str,
    baseline_graph: Path,
    case_root: Path,
    reader_config: ReaderConfig,
    run_phase: Callable[[PhaseRequest], PhaseResult],
) -> CaseResult:
    """Execute and validate baseline-reader -> refinement -> post-reader.

    ``run_phase`` will be a subprocess launcher in API runs.  Keeping it
    injectable lets the sequencing, isolation and provenance gates run with
    zero API calls.
    """

    paths = prepare_case_layout(
        baseline_graph=baseline_graph,
        case_root=case_root,
    )

    pre_request = PhaseRequest(
        phase="baseline-reader",
        case_id=case_id,
        question=question,
        graph_path=paths["baseline_reader"],
        sandbox=paths["baseline_reader"].parent,
        rebuild_index=True,
        read_only=True,
        reader_config=reader_config,
    )
    pre_input_hash = sha256_file(pre_request.graph_path)
    pre = run_phase(pre_request)
    _validate_phase_result(
        pre_request,
        pre,
        expected_hash_before=pre_input_hash,
    )

    refine_request = PhaseRequest(
        phase="refinement",
        case_id=case_id,
        question=question,
        graph_path=paths["refinement"],
        sandbox=paths["refinement"].parent,
        rebuild_index=True,
        read_only=False,
    )
    refine_input_hash = sha256_file(refine_request.graph_path)
    refined = run_phase(refine_request)
    _validate_phase_result(
        refine_request,
        refined,
        expected_hash_before=refine_input_hash,
    )

    shutil.copy2(paths["refinement"], paths["candidate"])
    _copy_graph(paths["candidate"], paths["post_reader"])
    candidate_hash = sha256_file(paths["candidate"])
    if candidate_hash != refined.graph_hash_after:
        raise ProtocolViolation("candidate snapshot does not match refinement output")

    post_request = PhaseRequest(
        phase="post-reader",
        case_id=case_id,
        question=question,
        graph_path=paths["post_reader"],
        sandbox=paths["post_reader"].parent,
        rebuild_index=True,
        read_only=True,
        reader_config=reader_config,
    )
    post_input_hash = sha256_file(post_request.graph_path)
    post = run_phase(post_request)
    _validate_phase_result(
        post_request,
        post,
        expected_hash_before=post_input_hash,
    )

    if pre_request.reader_config != post_request.reader_config:
        raise ProtocolViolation("baseline and candidate reader configs differ")
    if len({pre.process_id, refined.process_id, post.process_id}) != 3:
        raise ProtocolViolation("all three phases must run in separate processes")
    if len({pre.instance_id, refined.instance_id, post.instance_id}) != 3:
        raise ProtocolViolation("all three phases must use separate instances")
    if post.graph_hash_before != candidate_hash:
        raise ProtocolViolation("post-reader did not load the candidate graph")
    if (
        refined.action_count == 0
        and pre.graph_hash_before == candidate_hash
        and (
            pre.reader_context_hash != post.reader_context_hash
            or pre.answer != post.answer
        )
    ):
        raise ProtocolViolation(
            "zero-action identical graphs produced different reader contexts or answers"
        )

    result = CaseResult(
        case_id=case_id,
        pre_answer=pre.answer or "",
        post_answer=post.answer or "",
        baseline_graph_hash=pre.graph_hash_before,
        candidate_graph_hash=candidate_hash,
        graph_diff_summary=graph_diff_summary(
            paths["baseline_reader"],
            paths["candidate"],
        ),
        action_count=refined.action_count,
        reader_config=reader_config,
    )
    paths["manifest"].write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
