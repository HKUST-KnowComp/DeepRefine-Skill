from __future__ import annotations

from argparse import Namespace

import networkx as nx

from deeprefine_skill import cli, refine_runner


def test_refine_cli_gen_answer_defaults_off_and_can_be_enabled(monkeypatch):
    parsed: list[Namespace] = []

    def capture(args: Namespace) -> int:
        parsed.append(args)
        return 0

    monkeypatch.setattr(cli, "cmd_refine", capture)

    assert cli.main(["refine", "--query", "q"]) == 0
    assert parsed[-1].gen_answer is False

    assert cli.main(["refine", "--query", "q", "--gen-answer"]) == 0
    assert parsed[-1].gen_answer is True


def test_refine_from_history_forwards_gen_answer(monkeypatch, tmp_path):
    captured = {}

    def fake_run_refine(**kwargs):
        captured.update(kwargs)
        return {"mode": "dry-run"}

    monkeypatch.setattr(refine_runner, "run_refine", fake_run_refine)
    monkeypatch.setattr(
        refine_runner,
        "append_history",
        lambda _path, query, source: {"id": "q1", "query": query},
    )
    paths = {
        "history": tmp_path / "history.jsonl",
        "graph_json": tmp_path / "graph.json",
        "deeprefine_pkl": tmp_path / "deeprefine.pkl",
        "graphify_out": tmp_path,
    }

    refine_runner.refine_from_history(
        paths, {}, query="question", gen_answer=True
    )

    assert captured["gen_answer"] is True


def test_run_refine_passes_gen_answer_to_engine(monkeypatch, tmp_path):
    graph_path = tmp_path / "graph.json"
    graph_path.write_text("{}", encoding="utf-8")
    captured = {}

    class FakeDeepRefine:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.kg = nx.DiGraph()

        def refine(self, *, query):
            return None, None, None

    monkeypatch.setattr(refine_runner, "DeepRefine", FakeDeepRefine)
    monkeypatch.setattr(
        refine_runner, "make_clients", lambda _cfg: (object(), object())
    )
    monkeypatch.setattr(
        refine_runner,
        "load_or_build_data",
        lambda *_args, **_kwargs: ({}, {"KG": nx.DiGraph()}),
    )

    refine_runner.run_refine(
        graph_path=graph_path,
        cache_pkl=tmp_path / "deeprefine.pkl",
        history_path=tmp_path / "history.jsonl",
        log_dir=tmp_path / ".deeprefine",
        cfg={},
        queries=[{"id": "q1", "query": "question"}],
        gen_answer=True,
    )

    assert captured["if_gen_answer"] is True
