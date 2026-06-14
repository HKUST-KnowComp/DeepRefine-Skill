from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterator


def query_id(query: str, entry_id: str | None = None) -> str:
    """Stable id for a history row (matches append_history id field)."""
    if entry_id:
        return entry_id
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]


def _line_id(query: str) -> str:
    return query_id(query)


def append_history(
    path: Path,
    query: str,
    *,
    source: str = "user",
    refined: bool = False,
    entry_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    q = query.strip()
    entry = {
        "id": query_id(q, entry_id),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query": q,
        "source": source,
        "refined": refined,
    }
    if extra:
        entry.update(extra)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def iter_history(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def pending_queries(path: Path) -> list[dict[str, Any]]:
    seen: set[str] = set()
    pending: list[dict[str, Any]] = []
    for row in iter_history(path):
        q = row.get("query", "").strip()
        if not q or row.get("refined") is True:
            continue
        qid = row.get("id") or _line_id(q)
        if qid in seen:
            continue
        seen.add(qid)
        pending.append(row)
    return pending


def ensure_history_entry(
    path: Path,
    query: str,
    *,
    source: str = "user",
    entry_id: str | None = None,
    refined: bool = False,
    extra: dict[str, Any] | None = None,
) -> bool:
    qid = query_id(query.strip(), entry_id)
    for row in iter_history(path):
        row_id = row.get("id") or _line_id(row.get("query", ""))
        if row_id == qid:
            return False
    append_history(
        path,
        query,
        source=source,
        refined=refined,
        entry_id=qid,
        extra=extra,
    )
    return True


_HEADING_RE = re.compile(r"^#\s*Q:\s*(.+?)\s*$", re.MULTILINE)
_QUESTION_LINE_RE = re.compile(r"^question:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_question_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        # graphify memory frontmatter usually stores quoted strings.
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value)
                if isinstance(parsed, str):
                    return parsed.strip()
            except Exception:
                pass
    return value.strip().strip('"').strip("'")


def extract_query_from_memory_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            frontmatter = text[4:end]
            m = _QUESTION_LINE_RE.search(frontmatter)
            if m:
                q = _parse_question_value(m.group(1))
                if q:
                    return q
    m2 = _HEADING_RE.search(text)
    if m2:
        return m2.group(1).strip()
    return ""


def iter_memory_queries(memory_dir: Path) -> Iterator[tuple[str, Path]]:
    if not memory_dir.is_dir():
        return
    for md in sorted(memory_dir.glob("query_*.md")):
        q = extract_query_from_memory_markdown(md).strip()
        if q:
            yield q, md


def sync_history_from_memory(history_path: Path, memory_dir: Path) -> dict[str, int]:
    added = 0
    existing_ids: set[str] = set()
    for row in iter_history(history_path):
        q = row.get("query", "")
        row_id = row.get("id") or _line_id(q)
        if row_id:
            existing_ids.add(row_id)

    for query, md_path in iter_memory_queries(memory_dir):
        qid = _line_id(query)
        if qid in existing_ids:
            continue
        append_history(
            history_path,
            query,
            source="graphify_memory",
            refined=False,
            entry_id=qid,
            extra={"memory_file": str(md_path)},
        )
        existing_ids.add(qid)
        added += 1

    return {"added": added, "known": len(existing_ids)}


def mark_refined(path: Path, query_ids: set[str]) -> None:
    if not path.is_file() or not query_ids:
        return
    rows: list[dict[str, Any]] = list(iter_history(path))
    changed = False
    for row in rows:
        qid = row.get("id") or _line_id(row.get("query", ""))
        if qid in query_ids and not row.get("refined"):
            row["refined"] = True
            row["refined_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            changed = True
    if changed:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
