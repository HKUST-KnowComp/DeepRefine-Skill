from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "studies"
    / "s3-redocred"
    / "open_closed.py"
)
SPEC = importlib.util.spec_from_file_location("s3_open_closed", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
s3_open_closed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s3_open_closed)


class RecordingRefiner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def refine(self, **kwargs: Any) -> tuple[str, None, None]:
        self.calls.append(kwargs)
        return "", None, None


def test_paired_graphs_are_identical_and_have_no_passage_content() -> None:
    source = {
        "directed": True,
        "multigraph": False,
        "graph": {"suite": "redocred-mini-v1"},
        "nodes": [
            {"id": "doc::e0", "label": "Alice", "type": "entity"},
            {"id": "doc::e1", "label": "Bob", "type": "entity"},
            {
                "id": "doc.txt",
                "label": "private passage text",
                "type": "passage",
            },
        ],
        "links": [
            {"source": "doc::e0", "target": "doc::e1", "relation": "knows"},
            {"source": "doc::e0", "target": "doc.txt", "relation": "from"},
        ],
    }

    open_graph, closed_graph, graph_hash = s3_open_closed.prepare_paired_graphs(
        source
    )

    assert open_graph == closed_graph
    assert len(graph_hash) == 64
    assert [node["id"] for node in open_graph["nodes"]] == ["doc::e0", "doc::e1"]
    assert open_graph["links"] == [source["links"][0]]
    assert source["nodes"][-1]["type"] == "passage"


def test_open_closed_calls_only_differ_by_original_chunk() -> None:
    refiner = RecordingRefiner()
    sentinel = "STAGE3_OPEN_BOOK_SENTINEL_20261001"
    query = "What is the relationship between Alice and Bob?"

    s3_open_closed.run_stage3_query(
        refiner,
        query=query,
        context_mode="open",
        source_text=sentinel,
    )
    s3_open_closed.run_stage3_query(
        refiner,
        query=query,
        context_mode="closed",
        source_text=sentinel,
    )

    assert refiner.calls == [
        {"query": query, "original_chunk": sentinel},
        {"query": query, "original_chunk": None},
    ]
    assert refiner.calls[0]["query"] == refiner.calls[1]["query"]


def test_context_budget_is_deterministic_and_recorded() -> None:
    selected, context = s3_open_closed.select_source_text(
        "  abcdef  ",
        max_context_chars=4,
    )

    assert selected == "abcd"
    assert context["truncation"] == {
        "unit": "unicode_codepoints",
        "strategy": "prefix",
        "max_chars": 4,
        "input_chars": 6,
        "selected_chars": 4,
        "truncated": True,
    }
    assert len(context["input_sha256"]) == 64
    assert len(context["selected_sha256"]) == 64


def test_run_metadata_records_context_and_revisions() -> None:
    metadata = s3_open_closed.build_run_metadata(
        case_id="redocred-example",
        context_mode="closed",
        source_file="Example.txt",
        source_text="document text",
        graph_sha256="a" * 64,
        code_revisions={
            "deeprefine": {"commit": "1" * 40, "dirty": False},
            "deeprefine_skill": {"commit": "2" * 40, "dirty": True},
        },
    )

    assert metadata["context_mode"] == "closed"
    assert metadata["graph_sha256"] == "a" * 64
    assert metadata["context"]["source_file"] == "Example.txt"
    assert metadata["context"]["passed_to_original_chunk"] is False
    assert metadata["context"]["original_chunk_chars"] == 0
    assert metadata["context"]["truncation"]["max_chars"] == 12_000
    assert metadata["code_revisions"]["deeprefine_skill"]["dirty"] is True


def test_run_metadata_can_be_written(tmp_path: Path) -> None:
    destination = tmp_path / "metadata.json"
    metadata = {"study": "s3-redocred", "context_mode": "open"}

    s3_open_closed.write_run_metadata(destination, metadata)

    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert '"context_mode": "open"' in destination.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("query", "source_text", "message"),
    [
        ("", "context", "query"),
        ("question", "", "source text"),
    ],
)
def test_stage3_contract_rejects_empty_inputs(
    query: str,
    source_text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        s3_open_closed.build_refine_kwargs(
            query=query,
            context_mode="open",
            source_text=source_text,
        )


def test_stage3_contract_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        s3_open_closed.build_refine_kwargs(
            query="question",
            context_mode="nominal-open",
            source_text="context",
        )
