"""Mechanical gold extraction from a Python source tree (stdlib ``ast`` only).

The import relation is mechanically decidable, so gold for the import
subgraph is complete and objective: no human annotation, no self-authored
answer key.  For every project module the extractor enumerates:

- the module itself (entity gold),
- its top-level bound names (functions, classes, assignments, and
  import-bound names),
- project-internal import edges at two granularities:
  * module dependency edges (``A -> B`` whenever A contains at least one
    import statement resolving into module B, at any scoping depth),
  * module->symbol edges (``from B import name`` -> ``(A, B, name)``).

A symbol import also implies the module dependency: the symbol edge and
the dependency edge are both recorded.  Statements that resolve outside
the tree (stdlib, third-party packages) are ignored — gold only covers
what the AST can prove about this project.
"""

from __future__ import annotations

import ast
import io
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

# Directories that hold the importable package without contributing to its
# module names: ``src/urllib3/x.py`` must resolve as ``urllib3.x`` or every
# absolute in-package import silently misses the module table below
# (route-a dry-run 2026-09-05: up to 138 of 335 edges lost per repo).
# ``src/__init__.py`` (the container itself a package) is left unstripped.
CONTAINER_TOP_DIRS: tuple[str, ...] = ("src", "lib")

# Route-A pre-registered scope rule (docs/tmp/route-a-selection.md §5):
# developer surfaces excluded from BOTH gold extraction and the graphify
# corpus, so the exam and the corpus always see the same tree.  Opt-in per
# call — the default keeps v0.2.0 gold byte-identical (13/14/55).
ROUTE_A_EXCLUDED_TOP_DIRS: tuple[str, ...] = (
    "tests", "test", "docs", "doc", "examples", "example",
    "benchmarks", "benchmark", "tools", "scripts",
    "requirements", "ci_tools", "packaging",
)


@dataclass(frozen=True)
class GoldImport:
    """One project-internal import edge.

    ``target_symbol`` is empty for module dependency edges and holds the
    imported name for module->symbol edges.
    """

    source: str
    target_module: str
    target_symbol: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.target_module, self.target_symbol)


@dataclass(frozen=True)
class GoldAST:
    """Complete mechanical gold for one pinned source tree."""

    source_tag: str
    commit: str
    modules: tuple[str, ...]
    symbols: Mapping[str, tuple[str, ...]]
    imports: tuple[GoldImport, ...]
    file_count: int

    def module_dependencies(self) -> set[tuple[str, str]]:
        """Unique (source, target) module dependency pairs."""

        return {(edge.source, edge.target_module) for edge in self.imports}

    def symbol_imports(self) -> set[tuple[str, str, str]]:
        """Unique (source, target, symbol) module->symbol triples."""

        return {edge.key for edge in self.imports if edge.target_symbol}


def _collect_bound_names(tree: ast.Module) -> tuple[str, ...]:
    """Return top-level names bound by defs, classes, assigns, and imports.

    Conditional (``if``/``try``/``with``) top-level blocks are descended
    into; nested function/class bodies are not.
    """

    names: set[str] = set()

    def visit_body(body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    names.add(bound)
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                visit_body(stmt.body)
            elif isinstance(stmt, ast.If):
                visit_body(stmt.body)
                visit_body(stmt.orelse)
            elif isinstance(stmt, ast.Try):
                visit_body(stmt.body)
                for handler in stmt.handlers:
                    visit_body(handler.body)
                visit_body(stmt.orelse)
                visit_body(stmt.finalbody)

    visit_body(tree.body)
    return tuple(sorted(names))


def _resolve_base(
    package_parts: tuple[str, ...],
    level: int,
    module: str | None,
) -> tuple[str, ...] | None:
    """Resolve the base package of an ``ImportFrom`` to dotted parts.

    Returns ``None`` for imports that cannot resolve inside the tree
    (absolute names are resolved by the caller against the module map,
    so ``None`` here only means a malformed/out-of-tree relative import).
    """

    if level == 0:
        return tuple(module.split(".")) if module else None
    if not package_parts:
        return None
    go_up = level - 1
    if go_up >= len(package_parts):
        return None
    base = package_parts[: len(package_parts) - go_up]
    if module:
        base = (*base, *module.split("."))
    return base


def extract_gold(
    source_tree: str | Path,
    *,
    source_tag: str = "",
    commit: str = "",
    excluded_top_dirs: Sequence[str] = (),
) -> GoldAST:
    """Extract complete import-subgraph gold from a Python source tree.

    Deterministic: the same tree always yields the same gold.

    ``excluded_top_dirs`` drops whole top-level directories (tests, docs,
    ...) from the gold.  Callers must pass the same rule they use to build
    the graphify corpus so the exam and the corpus see one tree.  Leading
    ``src``/``lib`` container components (CONTAINER_TOP_DIRS) are always
    stripped from module names — ``src/pkg/x.py`` resolves as ``pkg.x`` —
    but never appear in the returned module paths, which stay tree-relative.
    """

    root = Path(source_tree)
    if not root.is_dir():
        raise ValueError(f"Source tree not found: {root}")

    py_files = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.is_file()
    )
    if excluded_top_dirs:
        excluded = frozenset(excluded_top_dirs)
        py_files = [rel for rel in py_files if rel.split("/", 1)[0] not in excluded]
    if not py_files:
        raise ValueError(f"No Python files under source tree: {root}")

    def module_parts(rel: str) -> tuple[str, ...]:
        parts = Path(rel).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if len(parts) > 1 and parts[0] in CONTAINER_TOP_DIRS:
            parts = parts[1:]
        return parts

    # Dotted module name -> file path, packages included via __init__.py.
    dotted: dict[str, str] = {}
    for rel in py_files:
        dotted[".".join(module_parts(rel))] = rel

    module_edges: set[tuple[str, str]] = set()
    symbol_edges: set[tuple[str, str, str]] = set()
    symbols: dict[str, tuple[str, ...]] = {}

    for rel in py_files:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        symbols[rel] = _collect_bound_names(tree)
        dir_parts = Path(rel).parts[:-1]
        if len(dir_parts) > 1 and dir_parts[0] in CONTAINER_TOP_DIRS:
            dir_parts = dir_parts[1:]
        package_parts = tuple(dir_parts)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = dotted.get(alias.name)
                    if target and target != rel:
                        module_edges.add((rel, target))
            elif isinstance(node, ast.ImportFrom):
                base_parts = _resolve_base(package_parts, node.level, node.module)
                if base_parts is None:
                    continue
                base_target = dotted.get(".".join(base_parts))
                for alias in node.names:
                    if alias.name == "*":
                        if base_target and base_target != rel:
                            module_edges.add((rel, base_target))
                        continue
                    # ``from pkg import mod`` — the alias may be a submodule.
                    sub_target = dotted.get(".".join((*base_parts, alias.name)))
                    if sub_target:
                        if sub_target != rel:
                            module_edges.add((rel, sub_target))
                        continue
                    # Otherwise a name bound inside the base module.
                    if base_target and base_target != rel:
                        module_edges.add((rel, base_target))
                        symbol_edges.add((rel, base_target, alias.name))

    imports = sorted(
        (
            *[GoldImport(src, tgt, "") for src, tgt in module_edges],
            *[GoldImport(src, tgt, sym) for src, tgt, sym in symbol_edges],
        ),
        key=lambda edge: edge.key,
    )
    return GoldAST(
        source_tag=source_tag,
        commit=commit,
        modules=tuple(py_files),
        symbols={module: tuple(sorted(names)) for module, names in symbols.items()},
        imports=tuple(imports),
        file_count=len(py_files),
    )


def resolve_commit(repo_root: str | Path, ref: str) -> str:
    """Return the commit hash of ``ref`` in ``repo_root`` ('' if unknown)."""

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return proc.stdout.strip()


def materialize_git_tree(repo_root: str | Path, ref: str = "HEAD") -> Path:
    """Extract ``ref``'s tree into a fresh temp directory.

    The caller owns the returned directory and must remove it.  Reading
    gold straight from a pinned git ref (rather than the working tree)
    is what keeps the extraction reproducible.
    """

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "archive", ref],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Cannot git-archive ref {ref!r}: {exc}") from exc

    target = Path(tempfile.mkdtemp(prefix="structeval-src-"))
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        try:
            archive.extractall(target, filter="data")
        except TypeError:  # Python < 3.12: no extraction filter support
            archive.extractall(target)
    return target


def gold_to_jsonable(gold: GoldAST) -> dict[str, object]:
    """Serialize gold for result.json provenance blocks."""

    return {
        "source_tag": gold.source_tag,
        "commit": gold.commit,
        "file_count": gold.file_count,
        "module_count": len(gold.modules),
        "module_dependency_count": len(gold.module_dependencies()),
        "symbol_import_count": len(gold.symbol_imports()),
    }


__all__ = [
    "CONTAINER_TOP_DIRS",
    "GoldAST",
    "GoldImport",
    "ROUTE_A_EXCLUDED_TOP_DIRS",
    "extract_gold",
    "gold_to_jsonable",
    "materialize_git_tree",
    "resolve_commit",
]
