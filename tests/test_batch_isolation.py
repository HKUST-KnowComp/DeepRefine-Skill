from __future__ import annotations

from deeprefine_skill.batch_isolation import run_query_isolated


class SuccessfulEngine:
    def __init__(self) -> None:
        self.kg = {"baseline": True}

    def refine(self, *, query: str):
        self.kg["last_query"] = query
        return "answer", "graph", "result"


class FailingAfterMutationEngine:
    def __init__(self) -> None:
        self.kg = {"baseline": True}

    def refine(self, *, query: str):
        self.kg["partial_change"] = query
        raise ValueError("malformed model response")


def test_success_returns_result_and_keeps_graph_change() -> None:
    engine = SuccessfulEngine()

    result, error = run_query_isolated(engine, "question")

    assert result == ("answer", "graph", "result")
    assert error is None
    assert engine.kg["last_query"] == "question"


def test_failure_returns_error_and_restores_starting_graph() -> None:
    engine = FailingAfterMutationEngine()

    result, error = run_query_isolated(engine, "bad question")

    assert result is None
    assert error == "ValueError: malformed model response"
    assert engine.kg == {"baseline": True}


def test_failed_query_does_not_contaminate_following_query() -> None:
    engine = FailingAfterMutationEngine()
    _result, error = run_query_isolated(engine, "bad question")
    assert error is not None

    engine.__class__ = SuccessfulEngine
    result, error = run_query_isolated(engine, "next question")

    assert error is None
    assert result == ("answer", "graph", "result")
    assert "partial_change" not in engine.kg
    assert engine.kg["last_query"] == "next question"
