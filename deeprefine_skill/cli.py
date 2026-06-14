"""DeepRefine CLI: `deeprefine cursor install` (graphify-style)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deeprefine_skill.history import (
    append_history,
    ensure_history_entry,
    iter_history,
    pending_queries,
    sync_history_from_memory,
)
from deeprefine_skill.installers import install_cursor_skill, uninstall_cursor_skill
from deeprefine_skill.paths import (
    env_defaults,
    find_deeprefine_repo,
    find_project_root,
    graphify_paths,
    setup_import_paths,
)


def _setup_repo_imports() -> None:
    setup_import_paths(find_deeprefine_repo())


def cmd_cursor_install(args: argparse.Namespace) -> int:
    dest = install_cursor_skill(project=args.project)
    scope = "project" if args.project else "user"
    print(f"Installed DeepRefine Cursor skill ({scope}) → {dest}")
    if args.project:
        print("Open this folder in Cursor, then use /deeprefine in chat.")
    return 0


def cmd_cursor_uninstall(args: argparse.Namespace) -> int:
    removed = uninstall_cursor_skill(project=args.project)
    if removed:
        scope = "project" if args.project else "user"
        print(f"Removed DeepRefine Cursor skill ({scope}).")
    else:
        print("Skill not installed at the selected scope.")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Alias for `deeprefine cursor install` (graphify-compatible naming)."""
    return cmd_cursor_install(args)


def cmd_history_add(args: argparse.Namespace) -> int:
    project = find_project_root()
    paths = graphify_paths(project)
    entry = append_history(
        paths["history"], args.query, source=args.source, refined=False
    )
    print(f"Recorded: {entry['id']} → {paths['history']}")
    return 0


def cmd_history_list(args: argparse.Namespace) -> int:
    project = find_project_root()
    paths = graphify_paths(project)
    if getattr(args, "sync_memory", False):
        memory_dir = paths["graphify_out"] / "memory"
        result = sync_history_from_memory(paths["history"], memory_dir)
        if result["added"] > 0:
            print(f"Synced {result['added']} query(s) from {memory_dir}")
    rows = (
        pending_queries(paths["history"])
        if args.pending
        else list(iter_history(paths["history"]))
    )
    if not rows and args.pending:
        print("No pending queries.")
        return 0
    for row in rows:
        flag = "refined" if row.get("refined") else "pending"
        print(f"[{flag}] {row.get('id', '?')}: {row.get('query', '')}")
    return 0


def cmd_history_sync_memory(args: argparse.Namespace) -> int:
    project = find_project_root()
    paths = graphify_paths(project)
    memory_dir = paths["graphify_out"] / "memory"
    result = sync_history_from_memory(paths["history"], memory_dir)
    print(f"Memory dir: {memory_dir}")
    print(f"History: {paths['history']}")
    print(f"Added: {result['added']}")
    print(f"Known query ids: {result['known']}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    _setup_repo_imports()
    from deeprefine_skill.adapter_graphify import load_or_build_data
    from deeprefine_skill.refine_runner import make_clients

    project = find_project_root()
    paths = graphify_paths(project)
    cfg = env_defaults()
    llm, encoder = make_clients(cfg)
    del llm
    load_or_build_data(
        paths["graph_json"],
        paths["reafiner_pkl"],
        encoder,
        rebuild=True,
    )
    print(f"Index cache: {paths['reafiner_pkl']}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply <refinement> actions (from agent loop) to graph.json."""
    from deeprefine_skill.agent_loop import load_trace, validate_trace

    project = find_project_root(Path(args.project_root) if args.project_root else None)
    paths = graphify_paths(project)
    text = Path(args.refinement_file).read_text(encoding="utf-8") if args.refinement_file else ""
    if not text.strip():
        print("Provide --refinement-file with <refinement>...</refinement> block", file=sys.stderr)
        return 1

    if not getattr(args, "skip_trace_check", False):
        if not args.trace_file:
            print(
                "Agent loop requires --trace-file (loop_trace_*.json). "
                "See SKILL.md or run: deeprefine loop validate --trace-file ...",
                file=sys.stderr,
            )
            return 1
        trace = load_trace(Path(args.trace_file))
        errs = validate_trace(trace, refinement_text=text)
        if errs:
            print("Loop trace validation failed (must match Reafiner.refine()):", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

    backup = paths["graph_backup"]
    if paths["graph_json"].is_file() and not backup.is_file():
        backup.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(paths["graph_json"], backup)
    changes = __import__(
        "deeprefine_skill.agent_graph", fromlist=["apply_refinement_text"]
    ).apply_refinement_text(paths["graph_json"], text)
    print(f"Applied {len(changes)} action(s) to {paths['graph_json']}")
    for c in changes:
        print(f"  - {c}")
    return 0


def cmd_loop_init(args: argparse.Namespace) -> int:
    from deeprefine_skill.agent_loop import default_trace, save_trace, trace_path_for_query

    project = find_project_root()
    paths = graphify_paths(project)
    trace = default_trace(args.query)
    out = Path(args.trace_file) if args.trace_file else trace_path_for_query(
        paths["history"].parent, args.query
    )
    save_trace(out, trace)
    print(f"Loop trace template: {out}")
    return 0


def cmd_loop_validate(args: argparse.Namespace) -> int:
    from deeprefine_skill.agent_loop import load_trace, validate_trace

    trace_path = Path(args.trace_file)
    refinement_text = None
    if args.refinement_file:
        refinement_text = Path(args.refinement_file).read_text(encoding="utf-8")
    elif trace_path.is_file():
        trace = load_trace(trace_path)
        ref = trace.get("refinement_action_file")
        if ref and Path(ref).is_file():
            refinement_text = Path(ref).read_text(encoding="utf-8")
    errs = validate_trace(load_trace(trace_path), refinement_text=refinement_text)
    if errs:
        print("INVALID — does not match Reafiner.refine() control flow:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("OK — loop trace matches Reafiner.refine() rules.")
    return 0


def cmd_loop_finish(args: argparse.Namespace) -> int:
    """Validate trace, append results log, mark history refined (agent loop step 7)."""
    import json
    import time

    from deeprefine_skill.agent_loop import (
        load_trace,
        reafiner_early_exit,
        validate_trace,
    )
    from deeprefine_skill.history import mark_refined, query_id

    project = find_project_root(Path(args.project_root) if args.project_root else None)
    paths = graphify_paths(project)
    trace_path = Path(args.trace_file)
    trace = load_trace(trace_path)
    refinement_text = None
    if args.refinement_file:
        refinement_text = Path(args.refinement_file).read_text(encoding="utf-8")
    errs = validate_trace(trace, refinement_text=refinement_text)
    if errs:
        print("Cannot finish — trace invalid:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    q = trace.get("query", "").strip()
    qid = trace.get("query_id") or query_id(q)
    ensure_history_entry(
        paths["history"],
        q,
        source="deeprefine_loop",
        entry_id=qid,
        refined=False,
        extra={"trace_file": str(trace_path)},
    )
    log = paths["history"].parent / f"refinement_results_{time.strftime('%Y%m%d')}.jsonl"
    entry = {
        "query": q,
        "query_id": qid,
        "interaction_history": trace.get("interaction_history"),
        "error_abduction_reason": trace.get("error_abduction_reason"),
        "refinement_action_raw": refinement_text,
        "early_exit": reafiner_early_exit(trace.get("interaction_history") or []),
        "mode": "agent-loop",
        "trace_file": str(trace_path),
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    mark_refined(paths["history"], {qid})
    print(f"Logged → {log}")
    print(f"Marked refined: {qid}")
    return 0


def cmd_refine(args: argparse.Namespace) -> int:
    _setup_repo_imports()
    from deeprefine_skill.refine_runner import refine_from_history

    project = find_project_root(Path(args.project_root) if args.project_root else None)
    paths = graphify_paths(project)
    if not args.query:
        sync_history_from_memory(paths["history"], paths["graphify_out"] / "memory")
    cfg = env_defaults()
    result = refine_from_history(
        paths,
        cfg,
        query=args.query,
        rebuild_index=args.rebuild_index,
    )
    print("\n--- DeepRefine summary ---")
    print(f"Queries processed: {result['queries_processed']}")
    print(f"Graph: {result['graph_path']} ({result['nodes']} nodes, {result['edges']} edges)")
    print(f"Log: {result['log_path']}")
    return 0


def _add_project_flag(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--project",
        action="store_true",
        default=None,
        help="Install to .cursor/skills in the current directory (default for cursor install)",
    )
    group.add_argument(
        "--user",
        action="store_true",
        help="Install to ~/.cursor/skills (all projects)",
    )


def _resolve_project(args: argparse.Namespace, *, default_project: bool) -> None:
    if getattr(args, "user", False):
        args.project = False
    elif getattr(args, "project", None) is True:
        args.project = True
    else:
        args.project = default_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deeprefine",
        description="DeepRefine: refine graphify-out/graph.json using query history",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # deeprefine cursor install | uninstall
    p_cursor = sub.add_parser("cursor", help="Cursor IDE integration")
    cursor_sub = p_cursor.add_subparsers(dest="cursor_cmd", required=True)

    p_ci = cursor_sub.add_parser("install", help="Install /deeprefine skill for Cursor")
    _add_project_flag(p_ci)
    p_ci.set_defaults(func=cmd_cursor_install, _default_project=True)

    p_cu = cursor_sub.add_parser("uninstall", help="Remove Cursor skill")
    _add_project_flag(p_cu)
    p_cu.set_defaults(func=cmd_cursor_uninstall, _default_project=True)

    # deeprefine install (alias)
    p_install = sub.add_parser(
        "install",
        help="Install Cursor skill (alias: deeprefine cursor install)",
    )
    _add_project_flag(p_install)
    p_install.set_defaults(func=cmd_install, _default_project=True)

    p_hist = sub.add_parser("history", help="Manage query history")
    hsub = p_hist.add_subparsers(dest="history_cmd", required=True)
    p_add = hsub.add_parser("add", help="Append a query to history")
    p_add.add_argument("--query", required=True)
    p_add.add_argument("--source", default="user")
    p_add.set_defaults(func=cmd_history_add)
    p_list = hsub.add_parser("list", help="List history entries")
    p_list.add_argument("--pending", action="store_true")
    p_list.add_argument(
        "--sync-memory",
        action="store_true",
        help="Import query_*.md under graphify-out/memory before listing",
    )
    p_list.set_defaults(func=cmd_history_list)
    p_sync = hsub.add_parser(
        "sync-memory",
        help="Import graphify-out/memory/query_*.md into deeprefine history",
    )
    p_sync.set_defaults(func=cmd_history_sync_memory)

    p_index = sub.add_parser("index", help="Rebuild FAISS cache from graph.json")
    p_index.add_argument("--rebuild", action="store_true", default=True)
    p_index.set_defaults(func=cmd_index)

    p_refine = sub.add_parser("refine", help="Run refinement on pending or given query")
    p_refine.add_argument("--query", default=None, help="Single query (also recorded)")
    p_refine.add_argument("--project-root", default=None)
    p_refine.add_argument("--rebuild-index", action="store_true")
    p_refine.set_defaults(func=cmd_refine)

    p_apply = sub.add_parser(
        "apply",
        help="Apply <refinement> actions (agent loop; requires --trace-file)",
    )
    p_apply.add_argument(
        "--refinement-file",
        required=True,
        help="File containing <refinement>insert_edge(...)|...</refinement>",
    )
    p_apply.add_argument(
        "--trace-file",
        required=False,
        help="loop_trace_<id>.json — validated against Reafiner.refine() before apply",
    )
    p_apply.add_argument(
        "--skip-trace-check",
        action="store_true",
        help="Bypass loop validation (not for /deeprefine agent mode)",
    )
    p_apply.add_argument("--project-root", default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_loop = sub.add_parser("loop", help="Agent Reafiner loop trace (no FAISS)")
    loop_sub = p_loop.add_subparsers(dest="loop_cmd", required=True)
    p_li = loop_sub.add_parser("init", help="Create loop_trace_<id>.json template")
    p_li.add_argument("--query", required=True)
    p_li.add_argument("--trace-file", default=None)
    p_li.set_defaults(func=cmd_loop_init)
    p_lv = loop_sub.add_parser("validate", help="Check trace matches Reafiner control flow")
    p_lv.add_argument("--trace-file", required=True)
    p_lv.add_argument("--refinement-file", default=None)
    p_lv.set_defaults(func=cmd_loop_validate)
    p_lf = loop_sub.add_parser("finish", help="Validate trace, log results, mark history refined")
    p_lf.add_argument("--trace-file", required=True)
    p_lf.add_argument("--refinement-file", default=None)
    p_lf.add_argument("--project-root", default=None)
    p_lf.set_defaults(func=cmd_loop_finish)

    args = parser.parse_args(argv)
    if hasattr(args, "_default_project"):
        _resolve_project(args, default_project=args._default_project)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
