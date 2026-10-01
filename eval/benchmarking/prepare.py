"""Prepare deterministic Re-DocRED, 2Wiki, and synthetic benchmark suites."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .suite import builtin_suite_path, sha256_file


SELECTION_SEED = "deeprefine-benchmark-v1"
SUPPORTED_PROFILES = {"quick", "readme"}
SUPPORTED_SUITES = {
    "synthetic-smoke-v1",
    "redocred-mini-v1",
    "2wiki-mini-v1",
}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _stable_digest(value: object) -> str:
    return hashlib.sha256(f"{SELECTION_SEED}:{value}".encode("utf-8")).hexdigest()


def _safe_file_name(value: object, *, suffix: str = ".txt") -> str:
    stem = _SAFE_NAME_RE.sub("-", str(value)).strip("-._")[:48] or "document"
    return f"{stem}-{_stable_digest(value)[:8]}{suffix}"


def _ensure_empty_output(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise ValueError(f"Output path is not a directory: {path}")
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load dataset {path}: {exc}") from exc
    if isinstance(raw, Mapping):
        for key in ("data", "documents", "examples"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise ValueError(f"Dataset {path} must contain an array of objects")
    return [dict(item) for item in raw]


def _hashed_take(
    items: Iterable[dict[str, Any]],
    count: int,
    *,
    key: Callable[[dict[str, Any]], object],
) -> list[dict[str, Any]]:
    ranked = sorted(items, key=lambda item: (_stable_digest(key(item)), str(key(item))))
    if len(ranked) < count:
        raise ValueError(f"Dataset has {len(ranked)} eligible items; need {count}")
    return ranked[:count]


def _write_jsonl(path: Path, items: Iterable[Mapping[str, Any]]) -> None:
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_lock(
    output_dir: Path,
    *,
    suite_id: str,
    profile: str,
    source: Mapping[str, Any],
) -> None:
    files = {
        str(path.relative_to(output_dir)).replace("\\", "/"): sha256_file(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "suite.lock.json"
    }
    lock = {
        "schema_version": 1,
        "suite_id": suite_id,
        "profile": profile,
        "selection_seed": SELECTION_SEED,
        "source": dict(source),
        "files": files,
    }
    (output_dir / "suite.lock.json").write_text(_json_text(lock), encoding="utf-8")


def _relation_mapping(source_path: Path) -> dict[str, str]:
    candidates = (
        source_path.parent / "rel_info.json",
        source_path.parent / "rel_info_full.json",
        source_path.parent / "relation_map.json",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, Mapping):
            continue
        result: dict[str, str] = {}
        for relation_id, value in raw.items():
            if isinstance(value, str):
                result[str(relation_id)] = value
            elif isinstance(value, Sequence) and value:
                result[str(relation_id)] = str(value[0])
            elif isinstance(value, Mapping):
                result[str(relation_id)] = str(
                    value.get("name") or value.get("label") or relation_id
                )
        return result
    return {}


def _redocred_triple_count(document: Mapping[str, Any]) -> int:
    labels = document.get("labels", [])
    return len(labels) if isinstance(labels, list) else 0


def _redocred_cross_sentence_ratio(document: Mapping[str, Any]) -> float:
    labels = document.get("labels", [])
    vertex_set = document.get("vertexSet", [])
    if not isinstance(labels, list) or not labels or not isinstance(vertex_set, list):
        return 0.0
    cross_sentence = 0
    valid = 0
    for label in labels:
        if not isinstance(label, Mapping):
            continue
        head = label.get("h")
        tail = label.get("t")
        if (
            not isinstance(head, int)
            or not isinstance(tail, int)
            or head >= len(vertex_set)
            or tail >= len(vertex_set)
        ):
            continue
        head_mentions = vertex_set[head] if isinstance(vertex_set[head], list) else []
        tail_mentions = vertex_set[tail] if isinstance(vertex_set[tail], list) else []
        head_sentences = {
            mention.get("sent_id")
            for mention in head_mentions
            if isinstance(mention, Mapping) and isinstance(mention.get("sent_id"), int)
        }
        tail_sentences = {
            mention.get("sent_id")
            for mention in tail_mentions
            if isinstance(mention, Mapping) and isinstance(mention.get("sent_id"), int)
        }
        if not head_sentences or not tail_sentences:
            continue
        valid += 1
        if head_sentences.isdisjoint(tail_sentences):
            cross_sentence += 1
    return cross_sentence / valid if valid else 0.0


def _redocred_key(document: Mapping[str, Any]) -> str:
    title = str(document.get("title", "")).strip()
    if title:
        return title
    return json.dumps(document, ensure_ascii=False, sort_keys=True)


def _stratified_redocred(
    documents: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    eligible = [
        document
        for document in documents
        if isinstance(document.get("vertexSet"), list)
        and isinstance(document.get("labels"), list)
        and _redocred_triple_count(document) > 0
    ]
    if len(eligible) < count:
        raise ValueError(
            f"Re-DocRED source has {len(eligible)} eligible documents; need {count}"
        )
    ordered = sorted(
        eligible,
        key=lambda item: (
            _redocred_triple_count(item),
            _redocred_cross_sentence_ratio(item),
            str(item.get("title", "")),
        ),
    )
    bucket_count = min(5, count)
    selected: list[dict[str, Any]] = []
    for bucket_index in range(bucket_count):
        start = bucket_index * len(ordered) // bucket_count
        end = (bucket_index + 1) * len(ordered) // bucket_count
        quota = count // bucket_count + int(bucket_index < count % bucket_count)
        bucket = sorted(
            ordered[start:end],
            key=lambda item: (_redocred_cross_sentence_ratio(item), _redocred_key(item)),
        )
        midpoint = len(bucket) // 2
        low = bucket[:midpoint]
        high = bucket[midpoint:]
        low_quota = quota // 2
        high_quota = quota - low_quota
        chosen: list[dict[str, Any]] = []
        if low_quota:
            chosen.extend(_hashed_take(low, low_quota, key=_redocred_key))
        if high_quota:
            chosen.extend(_hashed_take(high, high_quota, key=_redocred_key))
        selected.extend(chosen)
    return sorted(selected, key=lambda item: str(item.get("title", "")))


def _mention_aliases(entity: object) -> tuple[str, list[str]]:
    mentions = entity if isinstance(entity, list) else []
    aliases: list[str] = []
    for mention in mentions:
        if isinstance(mention, Mapping) and str(mention.get("name", "")).strip():
            aliases.append(str(mention["name"]))
    if not aliases:
        return "unknown entity", []
    return aliases[0], sorted(set(aliases[1:]))


def _prepare_redocred(
    source_path: Path,
    output_dir: Path,
    profile: str,
) -> dict[str, Any]:
    documents = _load_json_list(source_path)
    selected_count = 10 if profile == "quick" else 50
    selected = _stratified_redocred(documents, selected_count)
    relation_names = _relation_mapping(source_path)
    corpus_dir = output_dir / "corpus"
    corpus_dir.mkdir()
    cases: list[dict[str, Any]] = []
    corpus_records: list[dict[str, Any]] = []

    for index, document in enumerate(selected):
        title = str(document.get("title") or f"document-{index}")
        case_id = f"redocred-{_stable_digest(title)[:12]}"
        file_name = _safe_file_name(title)
        sentences = document.get("sents", [])
        text = "\n\n".join(
            " ".join(str(token) for token in sentence)
            for sentence in sentences
            if isinstance(sentence, list)
        )
        (corpus_dir / file_name).write_text(text.strip() + "\n", encoding="utf-8")
        corpus_records.append(
            {
                "id": case_id,
                "title": title,
                "text_file": f"corpus/{file_name}",
            }
        )

        entities: list[dict[str, Any]] = []
        vertex_set = document.get("vertexSet", [])
        for entity_index, entity in enumerate(vertex_set):
            label, aliases = _mention_aliases(entity)
            entities.append(
                {
                    "id": f"e{entity_index}",
                    "label": label,
                    "aliases": aliases,
                    "source_file": file_name,
                }
            )
        edges: list[dict[str, Any]] = []
        for label in document.get("labels", []):
            if not isinstance(label, Mapping):
                continue
            head = label.get("h")
            tail = label.get("t")
            relation_id = str(label.get("r", "")).strip()
            if not isinstance(head, int) or not isinstance(tail, int) or not relation_id:
                continue
            if head >= len(entities) or tail >= len(entities):
                continue
            relation = relation_names.get(relation_id, relation_id)
            edge: dict[str, Any] = {
                "source": f"e{head}",
                "relation": relation,
                "target": f"e{tail}",
            }
            if relation != relation_id:
                edge["accepted_relations"] = [relation_id]
            edges.append(edge)

        cases.append(
            {
                "id": case_id,
                "task": "intrinsic",
                "title": title,
                "source_files": [file_name],
                "directed": True,
                "gold_entities": entities,
                "gold_edges": edges,
            }
        )

    source = {
        "dataset": "Re-DocRED",
        "split": "dev",
        "path": str(source_path.resolve()),
        "sha256": sha256_file(source_path),
        "paper": "https://arxiv.org/abs/2205.12696",
    }
    suite = {
        "schema_version": 1,
        "suite_id": "redocred-mini-v1",
        "suite_version": "1",
        "profile": profile,
        "selection_seed": SELECTION_SEED,
        "source": source,
        "cases": cases,
    }
    (output_dir / "suite.json").write_text(_json_text(suite), encoding="utf-8")
    _write_jsonl(output_dir / "corpus.jsonl", corpus_records)
    _write_jsonl(output_dir / "queries.jsonl", [])
    _write_lock(
        output_dir,
        suite_id=suite["suite_id"],
        profile=profile,
        source=source,
    )
    return suite


_2WIKI_TYPES = ("compositional", "comparison", "inference", "bridge_comparison")


def _context_items(value: object) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            and len(item) >= 2
        ):
            title = str(item[0])
            sentences = item[1]
            if isinstance(sentences, list):
                result.append((title, [str(sentence) for sentence in sentences]))
    return result


def _evidence_edges(value: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            and len(item) >= 3
        ):
            result.append(
                {
                    "source": str(item[0]),
                    "relation": str(item[1]),
                    "target": str(item[2]),
                }
            )
    return result


def _supporting_facts(value: object) -> list[str]:
    result: list[str] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            and len(item) >= 2
        ):
            result.append(f"{item[0]}#{item[1]}")
    return result


def _seed_entities(edges: Sequence[Mapping[str, Any]]) -> list[str]:
    heads = [str(edge["source"]) for edge in edges]
    tails = {str(edge["target"]) for edge in edges}
    roots = [head for head in heads if head not in tails]
    return list(dict.fromkeys(roots or heads[:1]))


def _prepare_2wiki(
    source_path: Path,
    output_dir: Path,
    profile: str,
) -> dict[str, Any]:
    examples = _load_json_list(source_path)
    per_type = 4 if profile == "quick" else 16
    selected: list[dict[str, Any]] = []
    for question_type in _2WIKI_TYPES:
        typed = [
            item
            for item in examples
            if str(item.get("type", "")).replace("-", "_") == question_type
            and _evidence_edges(item.get("evidences"))
        ]
        selected.extend(
            _hashed_take(
                typed,
                per_type,
                key=lambda item: item.get("_id") or item.get("id") or item.get("question"),
            )
        )
    selected.sort(
        key=lambda item: (
            str(item.get("type", "")),
            str(item.get("_id") or item.get("id") or item.get("question")),
        )
    )

    corpus_dir = output_dir / "corpus"
    corpus_dir.mkdir()
    corpus_by_title: dict[str, tuple[str, list[str]]] = {}
    for example in selected:
        for title, sentences in _context_items(example.get("context")):
            corpus_by_title.setdefault(title, (_safe_file_name(title), sentences))
    corpus_records: list[dict[str, Any]] = []
    for title in sorted(corpus_by_title):
        file_name, sentences = corpus_by_title[title]
        (corpus_dir / file_name).write_text(
            "\n".join(sentence.strip() for sentence in sentences if sentence.strip())
            + "\n",
            encoding="utf-8",
        )
        corpus_records.append(
            {
                "id": _stable_digest(title)[:12],
                "title": title,
                "text_file": f"corpus/{file_name}",
            }
        )

    cases: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    for index, example in enumerate(selected):
        raw_id = example.get("_id") or example.get("id") or f"question-{index}"
        case_id = f"2wiki-{raw_id}"
        evidence = _evidence_edges(example.get("evidences"))
        answer = str(example.get("answer", "")).strip()
        answers = [answer] if answer else []
        endpoints = {
            str(edge["source"])
            for edge in evidence
        }.union(str(edge["target"]) for edge in evidence)
        answer_entities = [
            endpoint for endpoint in endpoints if endpoint.casefold() == answer.casefold()
        ] or answers
        cases.append(
            {
                "id": case_id,
                "task": "downstream",
                "question_type": str(example.get("type", "")).replace("-", "_"),
                "question": str(example.get("question", "")),
                "answers": answers,
                "seed_entities": _seed_entities(evidence),
                "answer_entities": answer_entities,
                "evidence_edges": evidence,
                "supporting_facts": _supporting_facts(example.get("supporting_facts")),
                "max_hops": min(4, max(1, len(evidence))),
            }
        )
        queries.append(
            {
                "case_id": case_id,
                "question": str(example.get("question", "")),
            }
        )

    source = {
        "dataset": "2WikiMultiHopQA",
        "split": "provided source",
        "path": str(source_path.resolve()),
        "sha256": sha256_file(source_path),
        "paper": "https://arxiv.org/abs/2011.01060",
    }
    suite = {
        "schema_version": 1,
        "suite_id": "2wiki-mini-v1",
        "suite_version": "1",
        "profile": profile,
        "selection_seed": SELECTION_SEED,
        "source": source,
        "cases": cases,
    }
    (output_dir / "suite.json").write_text(_json_text(suite), encoding="utf-8")
    _write_jsonl(output_dir / "corpus.jsonl", corpus_records)
    _write_jsonl(output_dir / "queries.jsonl", queries)
    _write_lock(
        output_dir,
        suite_id=suite["suite_id"],
        profile=profile,
        source=source,
    )
    return suite


def prepare_suite(
    suite_id: str,
    profile: str,
    output_dir: str | Path,
    *,
    source: str | Path | None = None,
) -> Path:
    """Prepare one deterministic suite and return its output directory."""

    if suite_id not in SUPPORTED_SUITES:
        raise ValueError(
            f"Unsupported suite {suite_id!r}; choose from {sorted(SUPPORTED_SUITES)}"
        )
    output_path = Path(output_dir).resolve()
    _ensure_empty_output(output_path)

    if suite_id == "synthetic-smoke-v1":
        if profile != "smoke":
            raise ValueError("synthetic-smoke-v1 only supports the smoke profile")
        source_dir = builtin_suite_path(suite_id)
        for item in source_dir.iterdir():
            destination = output_path / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
        return output_path

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(
            f"Unsupported profile {profile!r}; choose from {sorted(SUPPORTED_PROFILES)}"
        )
    if source is None:
        raise ValueError(f"--source is required for {suite_id}")
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise ValueError(f"Dataset source does not exist: {source_path}")
    if suite_id == "redocred-mini-v1":
        _prepare_redocred(source_path, output_path, profile)
    else:
        _prepare_2wiki(source_path, output_path, profile)
    return output_path
