# Stage 3 open/closed pilot plan

No real-model pilot has been started.  This document fixes the proposed scope
and stop conditions for approval.

## Scope

- one deterministic Re-DocRED document;
- its three frozen named target relations;
- one open and one closed run per target: six refinement runs total;
- one index build per condition;
- identical relation graph, query order, model, decoding, retrieval, and action
  settings; only `original_chunk` differs.

## Historical request evidence

The estimate uses detail rows only (`kind=llm|embed`) and excludes each JSONL
summary row.  Across the invalidated historical runs there were 50 documents
and 150 queries per condition:

| Condition | Detail requests | Errors | Requests/query p95 | Requests/query max |
|---|---:|---:|---:|---:|
| nominal open | 1,171 | 0 | 12 | 18 |
| closed | 1,186 | 0 | 12 | 16 |

Each historical document also used four index-build embedding requests.  The
median document totals were 24 requests per condition; the means were 23.42
and 23.72.  These runs are used only for request budgeting, not for quality or
open/closed conclusions.

## Proposed limits

- expected paired-document total: roughly 38–48 LLM/embedding requests;
- hard cap: 60 requests per condition, 120 requests overall;
- secondary cap: 20 LLM requests per condition, 40 overall;
- stop immediately on the first API error, prompt-contract failure, graph-hash
  mismatch, missing output, or evaluator parse failure;
- do not continue to the 50-document run without a separate review.

Every run must store the Stage 3 metadata record, usage detail rows, prompt
smoke result, graph hash, output artifact path, and both strict relation-label
and endpoint-pair metrics.
