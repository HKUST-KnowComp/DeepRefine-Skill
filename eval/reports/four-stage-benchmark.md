# Four-stage evaluation

This report is being rebuilt from audited artifacts. Headline values appear
only after their metric definition and provenance pass the checks in
[`eval/METRICS.md`](../METRICS.md).

| Study | Dataset/setup | Primary metric | Audited status |
|---|---|---|---|
| S1 Single-Repository Code Recovery | DeepRefine-Skill v0.2.0, 5 module + 3 symbol gaps | strict guided recovery | corrected single run: module 5/5; symbol 0/3; no baseline node/link loss |
| S2 Multi-Repository Code Recovery | urllib3, requests, python-dateutil, click | pooled strict module recovery | 16 candidate graphs rescored: module 16–26/35; strict symbol 0/142; smoke passed |
| S3 Re-DocRED Relation Recovery | 50 documents × 3 queried relations; paired open/closed | strict relation triple | corrected run complete: strict 0/150 both; endpoint pair open 38/150, closed 41/150 |
| S4 2WikiMultihopQA | 64 questions | paired pre/post EM and token F1 | historical result withdrawn; corrected rerun pending |

See each directory under `eval/studies/` for the protocol and limitation boundary.

## S2 audited executions

| Execution | Dependency strict | Symbol strict | New unverified import claims |
|---:|---:|---:|---:|
| 2026 | 19/35 (54.3%) | 0/142 | 38 |
| 2027 | 21/35 (60.0%) | 0/142 | 55 |
| 2028 | 16/35 (45.7%) | 0/142 | 52 |
| 2029 | 26/35 (74.3%) | 0/142 | 50 |

The dependency range is reproducible from existing artifacts. The historical
symbol percentage used a partial source+symbol match and is not a strict edge
recovery result. New unverified claims are reported as the counter-metric: a
higher insertion count is not automatically a better graph.

## S3 corrected paired execution

| Condition | Strict relation-label | Endpoint-pair diagnostic | Calls | LLM calls | API errors |
|---|---:|---:|---:|---:|---:|
| Open book | 0/150 (0%) | 38/150 (25.33%) | 1,215 | 445 | 0 |
| Closed book | 0/150 (0%) | 41/150 (27.33%) | 1,152 | 445 | 0 |

The paired endpoint outcomes were 32 both, 6 open-only, 9 closed-only, and 103
neither (two-sided exact paired test `p=0.607`). This single-seed run provides
no evidence of an open-book endpoint-coverage improvement. It does not show
that source context is generally ineffective: the primary strict metric is
zero in both conditions because free-form action relations do not match the
Re-DocRED relation vocabulary. The historical nominal-open runs remain
invalidated and are not combined with this corrected execution.
