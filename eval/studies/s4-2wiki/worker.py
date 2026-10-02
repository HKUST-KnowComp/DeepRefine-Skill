"""One-process worker for exactly one corrected Stage 4 phase."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Executing this nested script directly otherwise prefers an older installed
# deeprefine_skill package over the checked-out eval branch.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from protocol import PhaseRequest, PhaseResult, ReaderConfig, execute_case, sha256_file


def _load_env_file(path: Path | None) -> None:
    if path is None:
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class UsageRecorder:
    def __init__(self, path: Path, *, phase: str) -> None:
        self.path = path
        self.phase = phase
        self.rows: list[dict[str, Any]] = []

    def instrument(self, client: Any, *, kind: str, seed: int | None = None) -> None:
        endpoint = client.chat.completions if kind == "llm" else client.embeddings
        inner = endpoint.create

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if kind == "llm" and seed is not None:
                kwargs.setdefault("seed", seed)
            started = time.time()
            error = None
            try:
                response = inner(*args, **kwargs)
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                if error:
                    self._append(
                        kind=kind,
                        model=kwargs.get("model"),
                        elapsed_s=time.time() - started,
                        error=error,
                        seed=kwargs.get("seed"),
                        request_sha256=_request_hash(kwargs),
                    )
            usage = getattr(response, "usage", None)
            self._append(
                kind=kind,
                model=kwargs.get("model"),
                elapsed_s=time.time() - started,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                seed=kwargs.get("seed"),
                request_sha256=_request_hash(kwargs),
            )
            return response

        endpoint.create = wrapped

    def _append(self, **values: Any) -> None:
        row = {
            "record_type": "detail",
            "phase": self.phase,
            "ts": time.time(),
            **values,
        }
        self.rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _request_hash(kwargs: dict[str, Any]) -> str:
    safe = {
        key: value
        for key, value in kwargs.items()
        if key not in {"api_key", "authorization"}
    }
    payload = json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_reader_answer(
    *,
    cache_path: Path,
    question: str,
    context_hash: str,
    config: ReaderConfig,
    generate: Any,
) -> tuple[str, bool, str]:
    key_payload = {
        "question": question,
        "context_sha256": context_hash,
        "reader_config": asdict(config),
    }
    key = hashlib.sha256(
        json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.is_file()
        else {}
    )
    if key in cache:
        return str(cache[key]["full_answer"]), True, key
    full_answer = str(generate())
    cache[key] = {**key_payload, "full_answer": full_answer}
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    return full_answer, False, key


def _effective_action_strings(refinement: Any) -> list[str]:
    """Recover only the engine-filtered actions from its returned callables.

    The raw model text may contain actions rejected by grounding/conflict
    filters.  Conversely, applying the mutated in-memory DiGraph wholesale
    would collapse parallel baseline relations.  The closures are therefore
    the authoritative filtered action set; their bound defaults contain the
    resolved human-readable arguments.
    """

    if refinement is None:
        return []
    raw = refinement.refinement_action_raw or ""
    from deeprefine_skill.agent_graph import _parse_action_string, parse_refinement_block

    parsed = []
    try:
        parsed = [_parse_action_string(item) for item in parse_refinement_block(raw)]
    except ValueError:
        parsed = []

    actions: list[str] = []
    for action in refinement.refinement_action_list:
        names = set(action.__code__.co_names)
        defaults = tuple(action.__defaults__ or ())
        if "_insert_edge" in names and len(defaults) == 3:
            kind = "insert_edge"
            args = defaults
        elif "_replace_node" in names and len(defaults) == 2:
            kind = "replace_node"
            args = defaults
        elif "_delete_edge" in names and len(defaults) == 2:
            kind = "delete_edge"
            sub, obj = (str(value) for value in defaults)
            match = next(
                (
                    raw_args
                    for raw_kind, raw_args in parsed
                    if raw_kind == kind
                    and len(raw_args) == 3
                    and raw_args[0] == sub
                    and raw_args[2] == obj
                ),
                None,
            )
            if match is None:
                raise RuntimeError("could not recover relation for filtered delete_edge")
            args = tuple(match)
        else:
            raise RuntimeError("unknown refinement action closure")
        quoted = ", ".join(json.dumps(str(value), ensure_ascii=False) for value in args)
        actions.append(f"{kind}({quoted})")
    return actions


def _synthetic(args: argparse.Namespace, config: ReaderConfig) -> dict[str, Any]:
    before = sha256_file(args.graph)
    action_count = 0
    if args.phase == "refinement":
        payload = json.loads(args.graph.read_text(encoding="utf-8"))
        links_key = "links" if "links" in payload else "edges"
        payload.setdefault(links_key, []).append(
            {"source": "alpha", "target": "beta", "relation": "corrected"}
        )
        args.graph.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        action_count = 1
    after = sha256_file(args.graph)
    reader = args.phase != "refinement"
    return {
        "phase": args.phase,
        "source": "reader" if reader else "refinement",
        "graph_hash_before": before,
        "graph_hash_after": after,
        "process_id": os.getpid(),
        "instance_id": str(uuid.uuid4()),
        "answer": (
            "synthetic-baseline"
            if args.phase == "baseline-reader"
            else "synthetic-candidate" if args.phase == "post-reader" else None
        ),
        "action_count": action_count,
        "reader_config": vars(config) if reader else None,
        "index_rebuilt": reader,
    }


def _api(args: argparse.Namespace, config: ReaderConfig) -> dict[str, Any]:
    from deeprefine_skill.paths import (
        env_defaults,
        find_deeprefine_repo,
        setup_import_paths,
    )

    setup_import_paths(find_deeprefine_repo())
    from autorefiner.src.deeprefine import DeepRefine
    from deeprefine_skill.adapter_graphify import load_or_build_data
    from deeprefine_skill.agent_graph import apply_actions_to_graphify
    from deeprefine_skill.refine_runner import make_clients

    cfg = env_defaults()
    if cfg["DEEPREFINE_MODEL"] != config.model:
        raise RuntimeError("LLM model differs from frozen reader config")
    if cfg["DEEPREFINE_EMBED_MODEL"] != config.embedding_model:
        raise RuntimeError("embedding model differs from frozen reader config")

    usage = UsageRecorder(args.usage, phase=args.phase)
    llm, encoder = make_clients(cfg)
    usage.instrument(llm.client, kind="llm", seed=config.seed)
    usage.instrument(encoder.emb_client, kind="embedding")

    before = sha256_file(args.graph)
    cache = args.sandbox / "index" / "deeprefine.pkl"
    raw, data = load_or_build_data(args.graph, cache, encoder, rebuild=True)
    engine = DeepRefine(
        data=data,
        sentence_encoder=encoder,
        llm_generator=llm,
        base_top_k=config.base_top_k,
        max_hops=config.max_hops,
        max_triple_num=config.max_triple_num,
        max_triple_num_by_step=list(config.max_triple_num_by_step),
        history_horizon_size=config.history_horizon_size,
        if_gen_answer=args.phase != "refinement",
        seed=config.seed,
        ground_inserts=config.ground_inserts,
        ground_mode=config.ground_mode,
        skip_conflict_inserts=config.skip_conflict_inserts,
        skip_action_if_answerable=config.skip_action_if_answerable,
    )
    reader_context_hash = None
    if args.phase == "refinement":
        answer, _, refinement = engine.refine(
            query=args.question,
            # Candidate persistence is applied to the original Graphify JSON below.
            # This avoids collapsing parallel relations through NetworkX DiGraph.
            apply_actions=False,
        )
    else:
        # Fixed reader: deterministic graph retrieval followed by the engine's
        # existing answer generator.  No judgement/abduction/action trajectory
        # is part of the reader, and no answer prompt is duplicated here.
        retrieved_context, _ = engine.retriever.retrieve(
            args.question,
            topN=config.reader_top_k,
        )
        # Embedding services can return equal/near-equal hits in a different
        # order across independent index rebuilds.  Canonical ordering keeps
        # the reader prompt deterministic while preserving the retrieved set.
        retrieved_context = sorted(
            set(engine._sanitize_context_list(retrieved_context))
        )
        retrieved_context_hash = hashlib.sha256(
            "\n".join(retrieved_context).encode("utf-8")
        ).hexdigest()
        context = retrieved_context
        context_source = "rebuilt-index"
        # With an unchanged graph, independently calling a remote embedding
        # service can move one near-tied item across the Top-K boundary.  That
        # is provider noise, not a refinement effect.  The post reader still
        # rebuilds and queries its candidate index above, but its paired
        # evaluation input is frozen to the baseline reader's context when the
        # two graph snapshots are byte-identical.
        if (
            args.phase == "post-reader"
            and args.paired_baseline_context
            and args.paired_baseline_graph
            and sha256_file(args.graph) == sha256_file(args.paired_baseline_graph)
        ):
            baseline_retrieval = json.loads(
                args.paired_baseline_context.read_text(encoding="utf-8")
            )
            context = list(baseline_retrieval["context"])
            context_source = "paired-baseline-identical-graph"
        context_text = "\n".join(context)
        reader_context_hash = hashlib.sha256(
            context_text.encode("utf-8")
        ).hexdigest()
        (args.sandbox / "reader-retrieval.json").write_text(
            json.dumps(
                {
                    "question": args.question,
                    "top_k": config.reader_top_k,
                    "context": context,
                    "context_sha256": reader_context_hash,
                    "context_source": context_source,
                    "rebuilt_index_context": retrieved_context,
                    "rebuilt_index_context_sha256": retrieved_context_hash,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        full_answer, answer_cache_hit, answer_cache_key = _cached_reader_answer(
            cache_path=args.answer_cache,
            question=args.question,
            context_hash=reader_context_hash,
            config=config,
            generate=lambda: engine._generate_answer(args.question, context_text),
        )
        answer = engine.qa_judge.split_answer(full_answer)
        refinement = None
    effective_actions = (
        _effective_action_strings(refinement) if args.phase == "refinement" else []
    )
    applied_changes: list[str] = []
    if args.phase == "refinement":
        applied_changes = apply_actions_to_graphify(raw, effective_actions)
        # A no-action candidate must remain byte-identical to its baseline.
        if applied_changes:
            args.graph.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    action_count = len(applied_changes) if args.phase == "refinement" else 0
    after = sha256_file(args.graph)
    reader = args.phase != "refinement"
    return {
        "phase": args.phase,
        "source": "reader" if reader else "refinement",
        "graph_hash_before": before,
        "graph_hash_after": after,
        "process_id": os.getpid(),
        "instance_id": str(uuid.uuid4()),
        "answer": answer if reader else None,
        "action_count": action_count,
        "reader_config": vars(config) if reader else None,
        "index_rebuilt": True,
        "usage_detail_rows": len(usage.rows),
        "effective_actions": effective_actions if args.phase == "refinement" else [],
        "applied_changes": applied_changes,
        "reader_context_hash": reader_context_hash,
        "reader_answer_cache_hit": answer_cache_hit if reader else None,
        "reader_answer_cache_key": answer_cache_key if reader else None,
    }


def _add_phase_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--phase",
        choices=("baseline-reader", "refinement", "post-reader"),
        required=True,
    )
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--reader-config", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--answer-cache", type=Path, required=True)
    parser.add_argument("--paired-baseline-context", type=Path)
    parser.add_argument("--paired-baseline-graph", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--deeprefine-repo", type=Path)
    parser.add_argument("--synthetic", action="store_true")


def _run_phase(args: argparse.Namespace) -> int:

    _load_env_file(args.env_file)
    if args.deeprefine_repo:
        os.environ["DEEPREFINE_REPO"] = str(args.deeprefine_repo.resolve())
    config = ReaderConfig(**json.loads(args.reader_config.read_text(encoding="utf-8")))
    result = _synthetic(args, config) if args.synthetic else _api(args, config)
    args.result.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _read_phase_result(path: Path) -> PhaseResult:
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("reader_config") is not None:
        row["reader_config"] = ReaderConfig(**row["reader_config"])
    allowed = set(PhaseResult.__dataclass_fields__)
    return PhaseResult(**{key: value for key, value in row.items() if key in allowed})


def _run_case(args: argparse.Namespace) -> int:
    config = ReaderConfig(model=args.model, embedding_model=args.embedding_model)
    script = Path(__file__).resolve()

    def launch(request: PhaseRequest) -> PhaseResult:
        config_path = request.sandbox / "reader-config.json"
        result_path = request.sandbox / "phase-result.json"
        usage_path = request.sandbox / "api-usage.jsonl"
        log_path = request.sandbox / "worker.log"
        config_path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        command = [
            sys.executable,
            str(script),
            "phase",
            "--phase", request.phase,
            "--graph", str(request.graph_path),
            "--sandbox", str(request.sandbox),
            "--question", request.question,
            "--reader-config", str(config_path),
            "--result", str(result_path),
            "--usage", str(usage_path),
            "--answer-cache", str(args.case_root / "reader-answer-cache.json"),
            "--paired-baseline-context",
            str(args.case_root / "baseline-reader" / "reader-retrieval.json"),
            "--paired-baseline-graph",
            str(args.case_root / "baseline-reader" / "graph.json"),
        ]
        if args.env_file:
            command.extend(("--env-file", str(args.env_file)))
        if args.deeprefine_repo:
            command.extend(("--deeprefine-repo", str(args.deeprefine_repo)))
        if args.synthetic:
            command.append("--synthetic")
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        return _read_phase_result(result_path)

    result = execute_case(
        case_id=args.case_id,
        question=args.question,
        baseline_graph=args.baseline_graph,
        case_root=args.case_root,
        reader_config=config,
        run_phase=launch,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Corrected Stage 4 case runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    phase_parser = subparsers.add_parser("phase", help=argparse.SUPPRESS)
    _add_phase_arguments(phase_parser)

    case_parser = subparsers.add_parser("case", help="run one isolated pre/refine/post case")
    case_parser.add_argument("--case-id", required=True)
    case_parser.add_argument("--question", required=True)
    case_parser.add_argument("--baseline-graph", type=Path, required=True)
    case_parser.add_argument("--case-root", type=Path, required=True)
    case_parser.add_argument("--env-file", type=Path)
    case_parser.add_argument("--deeprefine-repo", type=Path)
    case_parser.add_argument("--model", required=True)
    case_parser.add_argument("--embedding-model", required=True)
    case_parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    return _run_phase(args) if args.command == "phase" else _run_case(args)


if __name__ == "__main__":
    raise SystemExit(main())
