"""Deterministic metrics used by the lightweight graph benchmark."""

from __future__ import annotations

import math
import re
import string
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Sequence

from .graph import normalize_text


@dataclass(frozen=True)
class PRF:
    """Precision/recall/F1 plus the counts that produced them."""

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def precision_recall_f1(tp: int, fp: int, fn: int) -> PRF:
    """Calculate PRF with documented empty-set behavior.

    Two empty sets score 1.0.  A zero denominator otherwise scores 0.0.
    """

    if tp < 0 or fp < 0 or fn < 0:
        raise ValueError("tp, fp, and fn must be non-negative")
    if tp == fp == fn == 0:
        return PRF(1.0, 1.0, 1.0, tp, fp, fn)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return PRF(precision, recall, f1, tp, fp, fn)


def set_prf(predicted: set[object], gold: set[object]) -> PRF:
    """Calculate exact set overlap PRF."""

    true_positive = len(predicted.intersection(gold))
    return precision_recall_f1(
        true_positive,
        len(predicted - gold),
        len(gold - predicted),
    )


def _tokens(value: object) -> list[str]:
    return re.findall(r"\w+", normalize_text(value), flags=re.UNICODE)


def _ngrams(tokens: Sequence[str], size: int) -> Counter[tuple[str, ...]]:
    if size <= 0:
        raise ValueError("ngram size must be positive")
    return Counter(tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1))


def sentence_bleu4(predicted: str, gold: str, *, epsilon: float = 0.1) -> float:
    """Small dependency-free BLEU-4 with method-1-style smoothing."""

    candidate = _tokens(predicted)
    reference = _tokens(gold)
    if not candidate or not reference:
        return 1.0 if candidate == reference else 0.0

    log_precisions = 0.0
    for size in range(1, 5):
        candidate_counts = _ngrams(candidate, size)
        reference_counts = _ngrams(reference, size)
        denominator = sum(candidate_counts.values())
        overlap = sum(
            min(count, reference_counts[gram])
            for gram, count in candidate_counts.items()
        )
        if denominator == 0:
            precision = epsilon
        elif overlap == 0:
            precision = epsilon / denominator
        else:
            precision = overlap / denominator
        log_precisions += 0.25 * math.log(max(precision, 1e-12))

    brevity_penalty = (
        1.0
        if len(candidate) >= len(reference)
        else math.exp(1.0 - len(reference) / len(candidate))
    )
    return brevity_penalty * math.exp(log_precisions)


def rouge2_precision(predicted: str, gold: str) -> float:
    """Return ROUGE-2 precision for one predicted/reference pair."""

    candidate_counts = _ngrams(_tokens(predicted), 2)
    reference_counts = _ngrams(_tokens(gold), 2)
    denominator = sum(candidate_counts.values())
    if denominator == 0:
        return 1.0 if candidate_counts == reference_counts else 0.0
    overlap = sum(
        min(count, reference_counts[gram])
        for gram, count in candidate_counts.items()
    )
    return overlap / denominator


def _maximum_assignment_sum(matrix: Sequence[Sequence[float]]) -> float:
    """Return maximum one-to-one assignment weight using Hungarian O(n^3)."""

    if not matrix or not matrix[0]:
        return 0.0
    rows = [list(row) for row in matrix]
    if any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("Similarity matrix must be rectangular")
    if len(rows) > len(rows[0]):
        rows = [list(column) for column in zip(*rows)]

    row_count = len(rows)
    column_count = len(rows[0])
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)

    for row_index in range(1, row_count + 1):
        p[0] = row_index
        minimum = [math.inf] * (column_count + 1)
        used = [False] * (column_count + 1)
        column_zero = 0
        while True:
            used[column_zero] = True
            active_row = p[column_zero]
            delta = math.inf
            next_column = 0
            for column_index in range(1, column_count + 1):
                if used[column_index]:
                    continue
                cost = -rows[active_row - 1][column_index - 1]
                reduced = cost - u[active_row] - v[column_index]
                if reduced < minimum[column_index]:
                    minimum[column_index] = reduced
                    way[column_index] = column_zero
                if minimum[column_index] < delta:
                    delta = minimum[column_index]
                    next_column = column_index
            for column_index in range(column_count + 1):
                if used[column_index]:
                    u[p[column_index]] += delta
                    v[column_index] -= delta
                else:
                    minimum[column_index] -= delta
            column_zero = next_column
            if p[column_zero] == 0:
                break
        while True:
            previous = way[column_zero]
            p[column_zero] = p[previous]
            column_zero = previous
            if column_zero == 0:
                break

    return sum(
        rows[p[column_index] - 1][column_index - 1]
        for column_index in range(1, column_count + 1)
        if p[column_index]
    )


def lexical_graph_score(
    predicted: Sequence[str],
    gold: Sequence[str],
    *,
    metric: str,
) -> dict[str, float]:
    """GraphJudge-style one-to-one lexical triple matching.

    ``metric`` is ``"bleu"`` or ``"rouge"``.  Scores are normalized by the
    predicted/gold graph sizes to obtain precision, recall, and F1.
    """

    if not predicted and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not predicted or not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    scorer = sentence_bleu4 if metric == "bleu" else rouge2_precision
    if metric not in {"bleu", "rouge"}:
        raise ValueError("metric must be 'bleu' or 'rouge'")
    matrix = [[scorer(candidate, reference) for reference in gold] for candidate in predicted]
    score = _maximum_assignment_sum(matrix)
    precision = score / len(predicted)
    recall = score / len(gold)
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def triple_sentence(triple: Sequence[object]) -> str:
    """Render a triple in the same component order used for lexical scoring."""

    if len(triple) != 3:
        raise ValueError("A triple must have exactly three components")
    from .graph import normalize_relation

    return "; ".join(
        (
            normalize_text(triple[0]),
            normalize_relation(triple[1]),
            normalize_text(triple[2]),
        )
    )


@lru_cache(maxsize=4)
def _bert_scorer(model_type: str) -> Any:
    try:
        from bert_score import BERTScorer
    except ImportError as exc:
        raise RuntimeError(
            "Semantic graph scoring requires "
            "`pip install 'deeprefine-cli[benchmark-semantic]'`"
        ) from exc
    return BERTScorer(
        model_type=model_type,
        lang="en",
        rescale_with_baseline=False,
    )


def bertscore_graph_score(
    predicted: Sequence[str],
    gold: Sequence[str],
    *,
    model_type: str = "roberta-large",
) -> dict[str, float]:
    """Optional GraphJudge-style BERTScore with one-to-one graph matching.

    The heavy dependency is imported only when this function is requested.
    Install ``deeprefine-cli[benchmark-semantic]`` to enable it.
    """

    if not predicted and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not predicted or not gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    candidates = [candidate for candidate in predicted for _reference in gold]
    references = [_reference for _candidate in predicted for _reference in gold]
    scorer = _bert_scorer(model_type)
    _precision, _recall, f1 = scorer.score(candidates, references)
    scores = [float(value) for value in f1]
    matrix = [
        scores[index * len(gold) : (index + 1) * len(gold)]
        for index in range(len(predicted))
    ]
    score = _maximum_assignment_sum(matrix)
    graph_precision = score / len(predicted)
    graph_recall = score / len(gold)
    graph_f1 = (
        2.0 * graph_precision * graph_recall / (graph_precision + graph_recall)
        if graph_precision + graph_recall
        else 0.0
    )
    return {
        "precision": graph_precision,
        "recall": graph_recall,
        "f1": graph_f1,
    }


_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", flags=re.IGNORECASE)
_PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation)


def normalize_answer(value: object) -> str:
    """Normalize a short QA answer using the repository's EM/F1 conventions."""

    text = normalize_text(value).replace("-", " ")
    text = text.translate(_PUNCT_TRANSLATION)
    text = _ARTICLES_RE.sub(" ", text)
    return " ".join(text.split())


def answer_exact_match(predicted: object, gold_answers: Iterable[object]) -> float:
    prediction = normalize_answer(predicted)
    answers = [normalize_answer(answer) for answer in gold_answers]
    return float(any(prediction == answer for answer in answers))


def _single_answer_f1(predicted: str, gold: str) -> float:
    predicted_tokens = normalize_answer(predicted).split()
    gold_tokens = normalize_answer(gold).split()
    if not predicted_tokens or not gold_tokens:
        return float(predicted_tokens == gold_tokens)
    common = Counter(predicted_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if not overlap:
        return 0.0
    precision = overlap / len(predicted_tokens)
    recall = overlap / len(gold_tokens)
    return 2.0 * precision * recall / (precision + recall)


def answer_token_f1(predicted: object, gold_answers: Iterable[object]) -> float:
    answers = [str(answer) for answer in gold_answers]
    if not answers:
        return 0.0
    return max(_single_answer_f1(str(predicted), answer) for answer in answers)


def hit_at_k(ranked_items: Sequence[object], gold_items: Iterable[object], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    gold = {normalize_text(item) for item in gold_items}
    return float(any(normalize_text(item) in gold for item in ranked_items[:k]))


def reciprocal_rank(ranked_items: Sequence[object], gold_items: Iterable[object]) -> float:
    gold = {normalize_text(item) for item in gold_items}
    for index, item in enumerate(ranked_items, start=1):
        if normalize_text(item) in gold:
            return 1.0 / index
    return 0.0


def supporting_recall(
    retrieved_items: Sequence[object],
    gold_items: Iterable[object],
    *,
    k: int | None = None,
) -> float:
    gold = {normalize_text(item) for item in gold_items}
    if not gold:
        return 1.0
    selected = retrieved_items if k is None else retrieved_items[:k]
    retrieved = {normalize_text(item) for item in selected}
    return len(gold.intersection(retrieved)) / len(gold)
