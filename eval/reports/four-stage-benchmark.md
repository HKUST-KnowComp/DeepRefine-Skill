# Four-stage evaluation

This report is being rebuilt from audited artifacts. Headline values appear
only after their metric definition and provenance pass the checks in
[`eval/METRICS.md`](../METRICS.md).

| Study | Dataset/setup | Primary metric | Audited status |
|---|---|---|---|
| S1 Single-Repository Code Recovery | DeepRefine-Skill v0.2.0, 5 module + 3 symbol gaps | strict guided recovery | corrected single run: module 5/5; symbol 0/3; no baseline node/link loss |
| S2 Multi-Repository Code Recovery | urllib3, requests, python-dateutil, click | pooled strict module recovery | 16 candidate graphs rescored: module 16–26/35; strict symbol 0/142; smoke passed |
| S3 Re-DocRED Relation Recovery | 150 queried missing relations | strict relation triple | strict 0/150; endpoint pair 31–41/150 is diagnostic; open-book ablation invalidated |
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
