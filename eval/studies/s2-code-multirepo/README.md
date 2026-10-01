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
