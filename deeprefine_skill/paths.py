from __future__ import annotations

import json
import os
import time
from pathlib import Path


def find_skill_root() -> Path:
    """Root of this repository (DeepRefine-Skill)."""
    return Path(__file__).resolve().parents[1]


def find_deeprefine_repo(start: Path | None = None) -> Path:
    """
    DeepRefine source repo (autorefiner/ + AutoSchemaKG/).

    Resolution order:
    1. DEEPREFINE_REPO environment variable
    2. Walk up from cwd for autorefiner/ + AutoSchemaKG/
    3. Sibling ../DeepRefine next to this skill repo
    """
    env = os.environ.get("DEEPREFINE_REPO", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if (root / "autorefiner").is_dir() and (root / "AutoSchemaKG").is_dir():
            return root
        raise FileNotFoundError(
            f"DEEPREFINE_REPO={env} is not a valid DeepRefine checkout "
            "(expected autorefiner/ and AutoSchemaKG/)."
        )

    here = (start or Path.cwd()).resolve()
    for parent in [here, *here.parents]:
        if (parent / "autorefiner").is_dir() and (parent / "AutoSchemaKG").is_dir():
            return parent

    sibling = find_skill_root().parent / "DeepRefine"
    if (sibling / "autorefiner").is_dir() and (sibling / "AutoSchemaKG").is_dir():
        return sibling.resolve()

    raise FileNotFoundError(
        "Could not locate the DeepRefine repository (need autorefiner/ and AutoSchemaKG/).\n"
        "Clone DeepRefine alongside this repo, or set:\n"
        "  export DEEPREFINE_REPO=/path/to/DeepRefine"
    )


def find_project_root(start: Path | None = None) -> Path:
    """User KB project root containing graphify-out/graph.json."""
    here = (start or Path.cwd()).resolve()
    for parent in [here, *here.parents]:
        if (parent / "graphify-out" / "graph.json").is_file():
            return parent
    return here


def graphify_paths(project_root: Path) -> dict[str, Path]:
    out = project_root / "graphify-out"
    deep = out / ".deeprefine"
    return {
        "graphify_out": out,
        "graph_json": out / "graph.json",
        "history": deep / "history.jsonl",
        "cache_dir": deep / "cache",
        "deeprefine_pkl": deep / "cache" / "deeprefine_data.pkl",
        "graph_backup": deep / "graph.json.bak",
        "checkpoints_metadata": deep / "checkpoints.json",
    }


def checkpoints_dir(project_root: Path) -> Path:
    """Directory holding checkpoint graph snapshots (one file per global seq)."""
    return project_root / "graphify-out" / ".deeprefine" / "checkpoints"


def run_backup_path(project_root: Path, seq: int) -> Path:
    """Per-run pre-state backup of graph.json: ``graph.json.bak.<seq>``.

    Taken right before the ``seq``-th apply writes the graph, so together
    with the post-state checkpoints it pins down exactly what changed in
    that single refinement run. Used by ``rollback --query`` to undo ONE
    refinement precisely instead of stepping back to a whole checkpoint.
    """
    return project_root / "graphify-out" / ".deeprefine" / f"graph.json.bak.{seq}"


def checkpoint_path(project_root: Path, seq: int) -> Path:
    """Return the checkpoint file path for a given global sequence number."""
    return checkpoints_dir(project_root) / f"graph.checkpoint.{seq}.json"


def checkpoints_metadata_path(project_root: Path) -> Path:
    """Return the path to the checkpoint timeline metadata registry."""
    return project_root / "graphify-out" / ".deeprefine" / "checkpoints.json"


def rollback_derivatives(project_root: Path) -> tuple[list[Path], list[Path]]:
    """Return proposal artifacts and index bundles invalidated by rollback.

    Proposal/review files describe the state that was current before the
    rollback. Index bundles are derived from ``graph.json`` and are considered
    fresh using only mtimes; because rollback restores with ``copy2``, a newer
    bundle can otherwise be reused with an older restored graph.
    """
    deep = project_root / "graphify-out" / ".deeprefine"
    proposal_patterns = (
        "proposed_refinement_actions_*.txt",
        "proposed_refinement_review.md",
        "proposed_refinement_review_*.md",
        "proposed_refinement_review_*.json",
    )
    proposals = sorted(
        {
            path
            for pattern in proposal_patterns
            for path in deep.glob(pattern)
            if path.is_file() or path.is_symlink()
        }
    )
    cache = deep / "cache"
    bundles = sorted(
        path
        for path in cache.glob("deeprefine_data*.pkl")
        if path.is_file() or path.is_symlink()
    )
    return proposals, bundles


def clear_rollback_derivatives(project_root: Path) -> tuple[int, int]:
    """Remove stale proposal files and index bundles after a successful restore."""
    proposals, bundles = rollback_derivatives(project_root)
    for path in (*proposals, *bundles):
        path.unlink(missing_ok=True)
    return len(proposals), len(bundles)


def load_checkpoint_metadata(path: Path) -> list[dict]:
    """Load checkpoint timeline metadata. Returns empty list if file doesn't exist."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_checkpoint_metadata(path: Path, data: list[dict]) -> None:
    """Atomically write checkpoint timeline metadata to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def create_checkpoint(
    graph_path: Path,
    metadata_path: Path,
    query_id: str = "",
    query_text: str = "",
) -> Path:
    """Create a post-state checkpoint of graph.json after a refinement apply.

    Checkpoints form a linear timeline (like git commits): every apply
    writes the FULL resulting graph as graph.checkpoint.<seq>.json, with
    seq monotonically increasing across ALL queries. Any checkpoint can
    later be restored independently.

    ``rollback <seq>`` restores a checkpoint AND resets the history marks
    of every later checkpoint's query to pending, so those queries can be
    refined again. Checkpoint files are always kept (rollback never deletes
    them), so every state stays comparable.

    Returns the checkpoint file path.
    """
    import shutil as _shutil

    project_root = graph_path.parent.parent
    meta = load_checkpoint_metadata(metadata_path)
    seq = (meta[-1]["seq"] if meta and "seq" in meta[-1] else 0) + 1

    dest = checkpoint_path(project_root, seq)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _shutil.copy2(graph_path, dest)

    meta.append({
        "seq": seq,
        "query_id": query_id,
        "query_text": query_text,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": str(dest),
    })
    save_checkpoint_metadata(metadata_path, meta)
    return dest


def get_checkpoint_by_seq(meta: list[dict], seq: int) -> dict | None:
    """Get a checkpoint entry by global seq."""
    for c in meta:
        if c.get("seq") == seq:
            return c
    return None


def setup_import_paths(deeprefine_repo: Path) -> None:
    import sys

    for p in (deeprefine_repo / "AutoSchemaKG", deeprefine_repo):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def env_defaults() -> dict[str, str]:
    shared_api_key = os.environ.get(
        "DEEPREFINE_API_KEY", os.environ.get("OPENAI_API_KEY", "")
    )
    return {
        # Empty URL means: use provider default endpoint in OpenAI SDK.
        "DEEPREFINE_LLM_URL": os.environ.get("DEEPREFINE_LLM_URL", "").strip(),
        "DEEPREFINE_EMBED_URL": os.environ.get("DEEPREFINE_EMBED_URL", "").strip(),
        "DEEPREFINE_LLM_API_KEY": os.environ.get(
            "DEEPREFINE_LLM_API_KEY", shared_api_key
        ).strip(),
        "DEEPREFINE_EMBED_API_KEY": os.environ.get(
            "DEEPREFINE_EMBED_API_KEY", shared_api_key
        ).strip(),
        "DEEPREFINE_MODEL": os.environ.get(
            "DEEPREFINE_MODEL", "gpt-4.1-mini"
        ),
        "DEEPREFINE_EMBED_MODEL": os.environ.get(
            "DEEPREFINE_EMBED_MODEL", "text-embedding-3-small"
        ),
    }
