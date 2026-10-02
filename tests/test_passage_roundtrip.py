from __future__ import annotations

import copy

from deeprefine_skill.passage_roundtrip import merge_passages, snapshot_passages


PASSAGE = {
    "id": "passage:src/a.py",
    "label": "full source text",
    "type": "passage",
    "source_file": "src/a.py",
    "custom": {"rank": 1},
}


def test_snapshot_selects_passages_and_copies_nested_data() -> None:
    raw = {
        "nodes": [
            {"id": "entity:a", "type": "entity"},
            copy.deepcopy(PASSAGE),
        ]
    }

    snapshot = snapshot_passages(raw)
    raw["nodes"][1]["custom"]["rank"] = 2

    assert snapshot == [PASSAGE]


def test_merge_restores_passage_verbatim() -> None:
    output = {"nodes": [{"id": "entity:a", "type": "entity"}], "links": []}

    merged = merge_passages(output, [PASSAGE])

    assert merged is output
    assert merged["nodes"][-1] == PASSAGE


def test_two_writebacks_keep_one_passage() -> None:
    first = merge_passages({"nodes": [{"id": "entity:a"}]}, [PASSAGE])
    second_snapshot = snapshot_passages(first)

    second = merge_passages({"nodes": [{"id": "entity:a"}]}, second_snapshot)

    passages = [node for node in second["nodes"] if node.get("type") == "passage"]
    assert passages == [PASSAGE]


def test_rebuilt_node_wins_id_collision() -> None:
    output = {"nodes": [{"id": PASSAGE["id"], "type": "entity"}]}

    merge_passages(output, [PASSAGE])

    assert output["nodes"] == [{"id": PASSAGE["id"], "type": "entity"}]


def test_duplicate_passage_ids_are_not_reintroduced() -> None:
    output = {"nodes": []}

    merge_passages(output, [PASSAGE, PASSAGE])

    assert output["nodes"] == [PASSAGE]


def test_no_passages_is_identity_noop() -> None:
    output = {"nodes": [{"id": "entity:a"}]}

    assert merge_passages(output, []) is output
    assert output == {"nodes": [{"id": "entity:a"}]}
