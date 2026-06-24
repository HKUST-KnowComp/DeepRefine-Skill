"""DeepRefine CLI — command-line entry point for the DeepRefine agent skill.

Provides subcommands for platform-specific skill installation (Cursor,
Copilot CLI, Gemini CLI), query-history management, FAISS index
rebuilding, dry-run refinement review, graph refinement, loop-trace
lifecycle management, and applying refinement actions to ``graph.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deeprefine_skill.history import (
    append_history,
    ensure_history_entry,
    iter_history,
    pending_queries,
    sync_history_from_memory,
)
from deeprefine_skill.installers import (
    copy_gemini_extension,
    gemini_extension_path,
    install_codex_skill,
    install_copilot_skill,
    install_cursor_skill,
    install_gemini_extension,
    link_gemini_extension,
    uninstall_codex_skill,
    uninstall_copilot_skill,
    uninstall_cursor_skill,
    uninstall_gemini_extension,
)
from deeprefine_skill.paths import (
    env_defaults,
    find_deeprefine_repo,
    find_project_root,
    graphify_paths,
    setup_import_paths,
)


def _setup_repo_imports() -> None:
    setup_import_paths(find_deeprefine_repo())


# ---------------------------------------------------------------------------
# Cursor handlers
# ---------------------------------------------------------------------------


def cmd_cursor_install(args: argparse.Namespace) -> int:
    """``deeprefine cursor install`` — install SKILL.md for Cursor."""
    dest = install_cursor_skill(project=args.project)
    scope = "project" if args.project else "user"
    print(f"Installed DeepRefine Cursor skill ({scope}) → {dest}")
    if args.project:
        print("Open this folder in Cursor, then use /deeprefine in chat.")
    return 0


def cmd_cursor_uninstall(args: argparse.Namespace) -> int:
    """``deeprefine cursor uninstall`` — remove the Cursor skill."""
    removed = uninstall_cursor_skill(project=args.project)
    if removed:
        scope = "project" if args.project else "user"
        print(f"Removed DeepRefine Cursor skill ({scope}).")
    else:
        print("Skill not installed at the selected scope.")
    return 0


# ---------------------------------------------------------------------------
# Copilot CLI handlers
# ---------------------------------------------------------------------------


def cmd_copilot_install(args: argparse.Namespace) -> int:
    """``deeprefine copilot install`` — install SKILL.md for Copilot CLI."""
    dest = install_copilot_skill(project=args.project)
    scope = "project" if args.project else "user"
    print(f"Installed DeepRefine Copilot CLI skill ({scope}) → {dest}")
    if args.project:
        print("Run /skills reload in Copilot CLI, then use /deeprefine.")
    return 0


def cmd_copilot_uninstall(args: argparse.Namespace) -> int:
    """``deeprefine copilot uninstall`` — remove the Copilot CLI skill."""
    removed = uninstall_copilot_skill(project=args.project)
    if removed:
        scope = "project" if args.project else "user"
        print(f"Removed DeepRefine Copilot CLI skill ({scope}).")
    else:
        print("Skill not installed at the selected scope.")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Alias for ``deeprefine cursor install`` (graphify-compatible naming)."""
    return cmd_cursor_install(args)


# ---------------------------------------------------------------------------
# Codex handlers
# ---------------------------------------------------------------------------


def cmd_codex_install(args: argparse.Namespace) -> int:
    """``deeprefine codex install`` - install SKILL.md for Codex."""
    dest = install_codex_skill(project=args.project)
    scope = "project" if args.project else "user"
    print(f"Installed DeepRefine Codex skill ({scope}) -> {dest}")
    if args.project:
        print("Restart or reload Codex, then invoke $deeprefine or /deeprefine.")
    return 0


def cmd_codex_uninstall(args: argparse.Namespace) -> int:
    """``deeprefine codex uninstall`` - remove the Codex skill."""
    removed = uninstall_codex_skill(project=args.project)
    if removed:
        scope = "project" if args.project else "user"
        print(f"Removed DeepRefine Codex skill ({scope}).")
    else:
        print("Skill not installed at the selected scope.")
    return 0


# ---------------------------------------------------------------------------
# Gemini CLI handlers
# ---------------------------------------------------------------------------


def cmd_gemini_path(args: argparse.Namespace) -> int:
    """``deeprefine gemini path`` — print the Gemini extension source path."""
    src = gemini_extension_path(prefer_repo=not args.bundled)
    print(src)
    return 0


def cmd_gemini_link(args: argparse.Namespace) -> int:
    """``deeprefine gemini link`` — link the extension with Gemini CLI's manager."""
    source = Path(args.source) if args.source else None
    try:
        src = link_gemini_extension(source)
    except Exception as exc:
        print(f"Failed to link Gemini CLI extension: {exc}", file=sys.stderr)
        return 1
    print(f"Linked DeepRefine Gemini CLI extension from → {src}")
    print("Restart Gemini CLI, then run: /extensions list")
    print("Expected commands: /deeprefine, /deeprefine:review, /deeprefine:apply")
    return 0


def cmd_gemini_install(args: argparse.Namespace) -> int:
    """``deeprefine gemini install`` — install the extension for Gemini CLI."""
    source = Path(args.source) if args.source else None
    if args.copy_only:
        target = Path(args.target_dir) if args.target_dir else None
        dest = copy_gemini_extension(target)
        print(f"Copied DeepRefine Gemini CLI extension → {dest}")
        print(
            "Restart Gemini CLI. If /extensions list still does not show it, "
            "use: deeprefine gemini link"
        )
        return 0
    try:
        src = install_gemini_extension(source, consent=not args.no_consent)
    except Exception as exc:
        print(
            f"Failed to install Gemini CLI extension with Gemini manager: {exc}",
            file=sys.stderr,
        )
        print("Fallback options:", file=sys.stderr)
        print("  deeprefine gemini link", file=sys.stderr)
        print("  deeprefine gemini install --copy-only", file=sys.stderr)
        return 1
    print(f"Installed DeepRefine Gemini CLI extension from → {src}")
    print("Restart Gemini CLI, then run: /extensions list")
    print("Expected commands: /deeprefine, /deeprefine:review, /deeprefine:apply")
    return 0


def cmd_gemini_uninstall(args: argparse.Namespace) -> int:
    """``deeprefine gemini uninstall`` — remove the Gemini CLI extension."""
    target = Path(args.target_dir) if args.target_dir else None
    try:
        removed = uninstall_gemini_extension(
            copy_only=args.copy_only, target_dir=target
        )
    except Exception as exc:
        print(f"Failed to uninstall Gemini CLI extension: {exc}", file=sys.stderr)
        return 1
    if removed:
        print("Removed DeepRefine Gemini CLI extension.")
    else:
        print("Gemini CLI extension not found at the selected location.")
    return 0


# ---------------------------------------------------------------------------
# History / index / review / apply / refine handlers
# ---------------------------------------------------------------------------


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
    """Apply ``<refinement>`` actions (from agent loop) to ``graph.json``.

    Runs an evidence-aware review before applying; refuses LOW-confidence
    actions unless ``--allow-low-confidence`` is passed.
    """
    from deeprefine_skill.action_review import render_review_markdown, review_refinement_text
    from deeprefine_skill.agent_loop import load_trace, validate_trace

    project = find_project_root(
        Path(args.project_root) if args.project_root else None
    )
    paths = graphify_paths(project)
    text = (
        Path(args.refinement_file).read_text(encoding="utf-8")
        if args.refinement_file
        else ""
    )
    if not text.strip():
        print(
            "Provide --refinement-file with <refinement>...</refinement> block",
            file=sys.stderr,
        )
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
            print(
                "Loop trace validation failed (must match Reafiner.refine()):",
                file=sys.stderr,
            )
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

    raw = json.loads(paths["graph_json"].read_text(encoding="utf-8"))
    reviews = review_refinement_text(raw, text, project_root=project)
    print(render_review_markdown(reviews))
    low_confidence = [review for review in reviews if review.confidence == "LOW"]
    if low_confidence and not args.allow_low_confidence:
        print(
            "Refusing to apply because LOW-confidence action(s) were detected. "
            "Review or rewrite the proposed actions, or rerun with "
            "--allow-low-confidence to override.",
            file=sys.stderr,
        )
        for review in low_confidence:
            print(f"  - {review.action}", file=sys.stderr)
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


def cmd_review(args: argparse.Namespace) -> int:
    """Validate and render evidence-aware proposed refinement actions."""
    from deeprefine_skill.action_review import write_review_files
    from deeprefine_skill.agent_loop import load_trace, validate_trace

    project = find_project_root(
        Path(args.project_root) if args.project_root else None
    )
    paths = graphify_paths(project)
    text = Path(args.refinement_file).read_text(encoding="utf-8")

    if args.trace_file:
        trace = load_trace(Path(args.trace_file))
        errs = validate_trace(trace, refinement_text=text)
        if errs:
            print("Loop trace validation failed:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1

    report_path = (
        Path(args.output)
        if args.output
        else paths["graphify_out"] / ".deeprefine" / "proposed_refinement_review.md"
    )
    json_path = Path(args.json_output) if args.json_output else None
    reviews, markdown = write_review_files(
        graph_path=paths["graph_json"],
        refinement_text=text,
        report_path=report_path,
        json_path=json_path,
    )
    print(markdown)
    print(f"Review saved: {report_path}")
    if json_path:
        print(f"Review JSON saved: {json_path}")
    print(f"No graph changes applied. Proposed actions: {len(reviews)}")
    return 0


def cmd_loop_init(args: argparse.Namespace) -> int:
    from deeprefine_skill.agent_loop import (
        default_trace,
        save_trace,
        trace_path_for_query,
    )

    project = find_project_root()
    paths = graphify_paths(project)
    trace = default_trace(args.query)
    out = (
        Path(args.trace_file)
        if args.trace_file
        else trace_path_for_query(paths["history"].parent, args.query)
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

    project = find_project_root(
        Path(args.project_root) if args.project_root else None
    )
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
    log = (
        paths["history"].parent
        / f"refinement_results_{time.strftime('%Y%m%d')}.jsonl"
    )
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

    project = find_project_root(
        Path(args.project_root) if args.project_root else None
    )
    paths = graphify_paths(project)
    if not args.query:
        sync_history_from_memory(paths["history"], paths["graphify_out"] / "memory")
    cfg = env_defaults()
    result = refine_from_history(
        paths,
        cfg,
        query=args.query,
        rebuild_index=args.rebuild_index,
        apply=args.apply,
    )
    print("\n--- DeepRefine summary ---")
    print(f"Mode: {result['mode']}")
    print(f"Queries processed: {result['queries_processed']}")
    print(
        f"Graph: {result['graph_path']} ({result['nodes']} nodes, {result['edges']} edges)"
    )
    print(f"Log: {result['log_path']}")
    if result["mode"] == "dry-run":
        print(
            "No graph changes applied. Review proposed actions, then run "
            "deeprefine apply if approved."
        )
    for row in result.get("summary", []):
        if row.get("action_file") or row.get("review_file"):
            print(f"Proposal [{row['id']}]:")
            if row.get("action_file"):
                print(f"  actions: {row['action_file']}")
            if row.get("review_file"):
                print(f"  review: {row['review_file']}")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------


def _add_project_flag(
    parser: argparse.ArgumentParser,
    *,
    project_help: str = "Install to .cursor/skills in the current directory (default for cursor install)",
    user_help: str = "Install to ~/.cursor/skills (all projects)",
) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--project",
        action="store_true",
        default=None,
        help=project_help,
    )
    group.add_argument(
        "--user",
        action="store_true",
        help=user_help,
    )


def _resolve_project(args: argparse.Namespace, *, default_project: bool) -> None:
    if getattr(args, "user", False):
        args.project = False
    elif getattr(args, "project", None) is True:
        args.project = True
    else:
        args.project = default_project


# ---------------------------------------------------------------------------
# Main CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deeprefine",
        description="DeepRefine: refine graphify-out/graph.json using query history",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # deeprefine cursor install | uninstall
    p_cursor = sub.add_parser("cursor", help="Cursor IDE integration")
    cursor_sub = p_cursor.add_subparsers(dest="cursor_cmd", required=True)

    p_ci = cursor_sub.add_parser(
        "install", help="Install /deeprefine skill for Cursor"
    )
    _add_project_flag(p_ci)
    p_ci.set_defaults(func=cmd_cursor_install, _default_project=True)

    p_cu = cursor_sub.add_parser("uninstall", help="Remove Cursor skill")
    _add_project_flag(p_cu)
    p_cu.set_defaults(func=cmd_cursor_uninstall, _default_project=True)

    # deeprefine copilot install | uninstall
    p_copilot = sub.add_parser("copilot", help="GitHub Copilot CLI integration")
    copilot_sub = p_copilot.add_subparsers(dest="copilot_cmd", required=True)

    p_copi = copilot_sub.add_parser(
        "install", help="Install /deeprefine skill for Copilot CLI"
    )
    _add_project_flag(
        p_copi,
        project_help=(
            "Install to .github/skills/deeprefine in the current directory "
            "(default for copilot install)"
        ),
        user_help="Install to ~/.copilot/skills/deeprefine (all projects)",
    )
    p_copi.set_defaults(func=cmd_copilot_install, _default_project=True)

    p_copu = copilot_sub.add_parser("uninstall", help="Remove Copilot CLI skill")
    _add_project_flag(
        p_copu,
        project_help=(
            "Remove from .github/skills/deeprefine in the current directory "
            "(default for copilot uninstall)"
        ),
        user_help="Remove from ~/.copilot/skills/deeprefine (all projects)",
    )
    p_copu.set_defaults(func=cmd_copilot_uninstall, _default_project=True)

    # deeprefine codex install | uninstall
    p_codex = sub.add_parser("codex", help="Codex skill integration")
    codex_sub = p_codex.add_subparsers(dest="codex_cmd", required=True)

    p_codi = codex_sub.add_parser(
        "install", help="Install $deeprefine skill for Codex"
    )
    _add_project_flag(
        p_codi,
        project_help=(
            "Install to .agents/skills/deeprefine in the current directory "
            "(default for codex install)"
        ),
        user_help="Install to ~/.codex/skills/deeprefine (all projects)",
    )
    p_codi.set_defaults(func=cmd_codex_install, _default_project=True)

    p_codu = codex_sub.add_parser("uninstall", help="Remove Codex skill")
    _add_project_flag(
        p_codu,
        project_help=(
            "Remove from .agents/skills/deeprefine in the current directory "
            "(default for codex uninstall)"
        ),
        user_help="Remove from ~/.codex/skills/deeprefine (all projects)",
    )
    p_codu.set_defaults(func=cmd_codex_uninstall, _default_project=True)

    # deeprefine gemini link | install | uninstall | path
    p_gemini = sub.add_parser("gemini", help="Gemini CLI integration")
    gemini_sub = p_gemini.add_subparsers(dest="gemini_cmd", required=True)

    p_gp = gemini_sub.add_parser(
        "path", help="Print the Gemini extension source path"
    )
    p_gp.add_argument(
        "--bundled",
        action="store_true",
        help="Print the bundled package template instead of preferring the repo root",
    )
    p_gp.set_defaults(func=cmd_gemini_path)

    p_gl = gemini_sub.add_parser(
        "link",
        help="Link this extension with Gemini CLI's official manager",
    )
    p_gl.add_argument(
        "--source",
        default=None,
        help="Extension root to link (default: repo root when available, "
        "otherwise bundled template)",
    )
    p_gl.set_defaults(func=cmd_gemini_link)

    p_gi = gemini_sub.add_parser(
        "install",
        help="Install this extension with Gemini CLI's official manager",
    )
    p_gi.add_argument(
        "--source",
        default=None,
        help="Extension root to install (default: bundled template)",
    )
    p_gi.add_argument(
        "--no-consent",
        action="store_true",
        help="Do not pass --consent to `gemini extensions install`",
    )
    p_gi.add_argument(
        "--copy-only",
        action="store_true",
        help="Manual fallback: copy files to ~/.gemini/extensions without Gemini manager",
    )
    p_gi.add_argument(
        "--target-dir",
        default=None,
        help="Copy-only destination (default: ~/.gemini/extensions/deeprefine-skill)",
    )
    p_gi.set_defaults(func=cmd_gemini_install)

    p_gu = gemini_sub.add_parser(
        "uninstall", help="Uninstall the Gemini CLI extension"
    )
    p_gu.add_argument(
        "--copy-only",
        action="store_true",
        help="Remove manual copy instead of calling Gemini manager",
    )
    p_gu.add_argument(
        "--target-dir",
        default=None,
        help="Copy-only destination (default: ~/.gemini/extensions/deeprefine-skill)",
    )
    p_gu.set_defaults(func=cmd_gemini_uninstall)

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

    p_refine = sub.add_parser(
        "refine", help="Run refinement on pending or given query"
    )
    p_refine.add_argument(
        "--query", default=None, help="Single query (also recorded)"
    )
    p_refine.add_argument("--project-root", default=None)
    p_refine.add_argument("--rebuild-index", action="store_true")
    p_refine.add_argument(
        "--apply",
        action="store_true",
        help="Write accepted CLI refine changes to graph.json. "
        "Default is dry-run proposal only.",
    )
    p_refine.set_defaults(func=cmd_refine)

    p_review = sub.add_parser(
        "review",
        help="Validate and show proposed <refinement> actions without changing graph.json",
    )
    p_review.add_argument("--refinement-file", required=True)
    p_review.add_argument("--trace-file", required=False)
    p_review.add_argument("--output", default=None, help="Markdown report path")
    p_review.add_argument(
        "--json-output", default=None, help="Optional JSON report path"
    )
    p_review.add_argument("--project-root", default=None)
    p_review.set_defaults(func=cmd_review)

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
    p_apply.add_argument(
        "--allow-low-confidence",
        action="store_true",
        help="Apply even when the review contains LOW-confidence actions.",
    )
    p_apply.add_argument("--project-root", default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_loop = sub.add_parser("loop", help="Agent Reafiner loop trace (no FAISS)")
    loop_sub = p_loop.add_subparsers(dest="loop_cmd", required=True)
    p_li = loop_sub.add_parser("init", help="Create loop_trace_<id>.json template")
    p_li.add_argument("--query", required=True)
    p_li.add_argument("--trace-file", default=None)
    p_li.set_defaults(func=cmd_loop_init)
    p_lv = loop_sub.add_parser(
        "validate", help="Check trace matches Reafiner control flow"
    )
    p_lv.add_argument("--trace-file", required=True)
    p_lv.add_argument("--refinement-file", default=None)
    p_lv.set_defaults(func=cmd_loop_validate)
    p_lf = loop_sub.add_parser(
        "finish", help="Validate trace, log results, mark history refined"
    )
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
