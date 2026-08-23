"""Suite schema loading and reproducibility helpers."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_SCHEMA_VERSION = 1


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def builtin_suite_path(suite_id: str) -> Path:
    """Resolve an unpacked built-in suite directory."""

    root = resources.files("deeprefine_skill").joinpath("benchmark_suites", suite_id)
    path = Path(str(root))
    if not (path / "suite.json").is_file():
        raise ValueError(f"Unknown built-in benchmark suite: {suite_id}")
    return path


def resolve_suite_path(value: str | Path) -> Path:
    """Resolve a directory, suite.json path, or built-in suite ID."""

    path = Path(value)
    if path.is_dir():
        path = path / "suite.json"
    if path.is_file():
        return path.resolve()
    return (builtin_suite_path(str(value)) / "suite.json").resolve()


def verify_suite_lock(suite_directory: str | Path) -> None:
    """Verify files listed by an optional ``suite.lock.json``."""

    root = Path(suite_directory).resolve()
    lock_path = root / "suite.lock.json"
    if not lock_path.is_file():
        return
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load suite lock {lock_path}: {exc}") from exc
    files = lock.get("files")
    if not isinstance(files, Mapping):
        raise ValueError(f"Suite lock has no files mapping: {lock_path}")
    for relative, expected in files.items():
        target = (root / str(relative)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Suite lock path escapes suite directory: {relative}") from exc
        if not target.is_file():
            raise ValueError(f"Suite lock file is missing: {relative}")
        actual = sha256_file(target)
        if actual != str(expected).casefold():
            raise ValueError(
                f"Suite lock checksum mismatch for {relative}: "
                f"expected {expected}, got {actual}"
            )


def load_suite(value: str | Path | Mapping[str, Any]) -> tuple[dict[str, Any], Path | None]:
    """Load and minimally validate a benchmark suite.

    Returns ``(suite, suite_directory)``.  Inline mappings have no directory.
    """

    if isinstance(value, Mapping):
        suite = dict(value)
        suite_dir = None
    else:
        suite_path = resolve_suite_path(value)
        verify_suite_lock(suite_path.parent)
        try:
            suite = json.loads(suite_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load suite {suite_path}: {exc}") from exc
        suite_dir = suite_path.parent

    if suite.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported suite schema_version "
            f"{suite.get('schema_version')!r}; expected {SUPPORTED_SCHEMA_VERSION}"
        )
    for field_name in ("suite_id", "suite_version", "profile", "cases"):
        if field_name not in suite:
            raise ValueError(f"Suite is missing required field: {field_name}")
    if not isinstance(suite["cases"], list):
        raise ValueError("Suite 'cases' must be an array")

    seen_ids: set[str] = set()
    for index, case in enumerate(suite["cases"]):
        if not isinstance(case, Mapping):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = str(case.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"cases[{index}] is missing id")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id: {case_id}")
        seen_ids.add(case_id)
        if case.get("task") not in {"intrinsic", "downstream"}:
            raise ValueError(
                f"cases[{index}].task must be 'intrinsic' or 'downstream'"
            )
    return suite, suite_dir


def load_predictions(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Load case-keyed prediction JSONL."""

    if path is None:
        return {}
    prediction_path = Path(path)
    result: dict[str, dict[str, Any]] = {}
    try:
        lines = prediction_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot load predictions {prediction_path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid prediction JSON on line {line_number}: {exc}"
            ) from exc
        if not isinstance(item, dict) or not str(item.get("case_id", "")).strip():
            raise ValueError(
                f"Prediction line {line_number} must contain a case_id"
            )
        case_id = str(item["case_id"])
        if case_id in result:
            raise ValueError(f"Duplicate prediction case_id: {case_id}")
        result[case_id] = item
    return result
