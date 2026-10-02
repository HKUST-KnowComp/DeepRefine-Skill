"""Capture DeepRefine's real final action prompt without making API calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


DEFAULT_SENTINEL = "STAGE3_OPEN_BOOK_SENTINEL_20261001"


class CapturingGenerator:
    """LLM stand-in that records messages and returns a valid no-op action."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate_response(self, messages: list[dict[str, str]], **_: Any) -> str:
        self.calls.append(copy.deepcopy(messages))
        return "<refinement></refinement>"


def _git_revision(repo: Path) -> dict[str, Any]:
    resolved = repo.resolve()
    commit = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(resolved), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def _load_deeprefine(deeprefine_repo: Path) -> type[Any]:
    repo = deeprefine_repo.resolve()
    autoschema = repo / "AutoSchemaKG"
    if not (repo / "autorefiner/src/deeprefine.py").is_file():
        raise FileNotFoundError(f"DeepRefine source not found under {repo}")
    for item in (str(autoschema), str(repo)):
        if item not in sys.path:
            sys.path.insert(0, item)
    from autorefiner.src.deeprefine import DeepRefine

    return DeepRefine


def capture_action_prompt(
    deeprefine_repo: Path,
    *,
    original_text: str,
) -> str:
    """Invoke the research engine's action method and return its final user prompt."""

    deeprefine_class = _load_deeprefine(deeprefine_repo)
    generator = CapturingGenerator()
    refiner = object.__new__(deeprefine_class)
    refiner.llm_generator = generator
    refiner.max_format_retry = 0
    refiner.max_actions = 10
    messages = [
        {"role": "system", "content": "captured Stage 3 smoke trajectory"},
        {"role": "assistant", "content": "<abduction>smoke</abduction>"},
    ]
    with redirect_stdout(io.StringIO()):
        refiner._kg_refinement_action_messages(
            messages,
            original_text=original_text,
            query="What is the relationship between Alice and Bob?",
            triples=[
                {"subject": "Alice", "relation": "related to", "object": "Bob"}
            ],
            error_abduction_reason="smoke",
        )
    if len(generator.calls) != 1:
        raise AssertionError("expected exactly one captured action-model call")
    return generator.calls[0][-1]["content"]


def run_prompt_smoke(
    deeprefine_repo: Path,
    *,
    sentinel: str = DEFAULT_SENTINEL,
    skill_repo: Path | None = None,
) -> dict[str, Any]:
    """Assert the open/closed prompt contract against the real engine method."""

    open_prompt = capture_action_prompt(deeprefine_repo, original_text=sentinel)
    closed_prompt = capture_action_prompt(deeprefine_repo, original_text="")
    if sentinel not in open_prompt:
        raise AssertionError("open action prompt does not contain the sentinel")
    if sentinel in closed_prompt:
        raise AssertionError("closed action prompt contains the sentinel")
    if open_prompt.replace(sentinel, "") != closed_prompt:
        raise AssertionError("open/closed action prompts differ beyond source context")
    result = {
        "sentinel": sentinel,
        "open_contains_sentinel": True,
        "closed_contains_sentinel": False,
        "only_difference_is_context": True,
        "open_prompt_sha256": hashlib.sha256(open_prompt.encode("utf-8")).hexdigest(),
        "closed_prompt_sha256": hashlib.sha256(closed_prompt.encode("utf-8")).hexdigest(),
        "deeprefine_revision": _git_revision(deeprefine_repo),
        "prompt_smoke_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    if skill_repo is not None:
        result["deeprefine_skill_revision"] = _git_revision(skill_repo)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deeprefine-repo", type=Path, required=True)
    parser.add_argument(
        "--skill-repo",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument("--sentinel", default=DEFAULT_SENTINEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(
        run_prompt_smoke(
            args.deeprefine_repo,
            sentinel=args.sentinel,
            skill_repo=args.skill_repo,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
