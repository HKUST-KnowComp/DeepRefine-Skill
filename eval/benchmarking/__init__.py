"""Offline, reproducible benchmarks for Graphify/DeepRefine graphs.

The default benchmark implementation intentionally depends only on the Python
standard library.  Public helpers are imported lazily by the CLI so the
existing DeepRefine commands keep their current dependency footprint.
"""

from .evaluator import evaluate_suite
from .prepare import prepare_suite
from .report import render_markdown

__all__ = ["evaluate_suite", "prepare_suite", "render_markdown"]
