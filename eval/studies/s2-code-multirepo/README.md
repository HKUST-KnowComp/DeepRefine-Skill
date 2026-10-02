# S2 — Multi-Repository Code Recovery

## Question

Does strict guided import-edge recovery generalize across multiple real-world
repository layouts?

## Repositories

The frozen study uses urllib3, requests, python-dateutil, and click. Every run
must record the exact source revision and AST scope rule.

## Protocol

- Use one frozen baseline and missing-edge query set per repository.
- Smoke test with one query per repository before any full rerun.
- Reuse existing candidate graphs for offline rescoring when generation logic
  has not changed.
- Aggregate counts across repositories per execution; do not average percentages
  from unequal denominators.

## Primary metric

Strict module-dependency recovery over the pooled missing-edge denominator.

Historical symbol results must be rescored: an empty target module is not a
wildcard. Source+symbol partial matches may be reported only as a diagnostic.

## Audited result handling

The reorganized pipeline passed a one-query smoke on all four repositories
without losing baseline nodes or edges. A full model rerun was deliberately
not repeated because index rebuilding dominated the cost. Instead, the 16
existing candidate graphs were rescored offline with the corrected strict
matcher.

Generate both report formats with:

```bash
python eval/studies/s2-code-multirepo/aggregate.py \
  --input-root /path/to/s2-offline-rescore \
  --output /tmp/s2-summary.md \
  --json-output eval/reports/s2-code-multirepo.json
```
