from __future__ import annotations

import os
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
        "reafiner_pkl": deep / "cache" / "reafiner_data.pkl",
        "graph_backup": deep / "graph.json.bak",
    }


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
